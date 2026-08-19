const OKX_BASE = "https://www.okx.com";
const FALLBACK_CNY_RATE = 7.2;
const TE_BASE = "https://api.tradingeconomics.com";
const RECENT_MACRO_KEEP_MS = 7 * 24 * 60 * 60 * 1000;

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
      "Pragma": "no-cache",
    },
  });
}

function b64(buffer) {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function hmacSha256Base64(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return b64(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message)));
}

async function okxGet(env, path) {
  const timestamp = new Date().toISOString();
  const signature = await hmacSha256Base64(env.OKX_API_SECRET, `${timestamp}GET${path}`);
  const response = await fetch(`${OKX_BASE}${path}`, {
    headers: {
      "OK-ACCESS-KEY": env.OKX_API_KEY,
      "OK-ACCESS-SIGN": signature,
      "OK-ACCESS-TIMESTAMP": timestamp,
      "OK-ACCESS-PASSPHRASE": env.OKX_API_PASSPHRASE,
      "Content-Type": "application/json",
    },
    cf: { cacheTtl: 0, cacheEverything: false },
  });
  const payload = await response.json();
  if (!response.ok || payload.code !== "0") {
    throw new Error(`OKX ${path} failed: ${payload.msg || response.status}`);
  }
  return payload.data || [];
}

async function cnyRate() {
  try {
    const response = await fetch("https://api.coinbase.com/v2/exchange-rates?currency=USDT", {
      cf: { cacheTtl: 60 },
    });
    const payload = await response.json();
    const rate = Number(payload?.data?.rates?.CNY);
    if (Number.isFinite(rate) && rate > 0) return { rate, source: "Coinbase USDT/CNY" };
  } catch {
    // Fall through to the stable fallback used by the dashboard.
  }
  return { rate: FALLBACK_CNY_RATE, source: "fallback" };
}

function beijingWeekKey(now = new Date()) {
  const bj = new Date(now.getTime() + 8 * 60 * 60 * 1000);
  const day = bj.getUTCDay() || 7;
  bj.setUTCDate(bj.getUTCDate() - day + 1);
  bj.setUTCHours(0, 0, 0, 0);
  return bj.toISOString().slice(0, 10);
}

function weeklyRiskPct(equityCny) {
  if (equityCny < 10000) return 0.4;
  if (equityCny < 30000) return 0.3;
  if (equityCny < 100000) return 0.2;
  return 0.12;
}

function parsePositions(positions, instruments) {
  const inst = instruments.find((item) => item.instId === "BTC-USDT-SWAP") || {};
  const contractValue = Number(inst.ctVal || 0.01);
  return positions
    .filter((item) => item.instId === "BTC-USDT-SWAP" && Math.abs(Number(item.pos || 0)) > 0)
    .map((item) => {
      const rawPos = Number(item.pos || 0);
      const posSide = item.posSide === "net" ? (rawPos < 0 ? "short" : "long") : item.posSide;
      const entryPrice = Number(item.avgPx || 0);
      const markPrice = Number(item.markPx || 0);
      const quantityBtc = Math.abs(rawPos) * contractValue;
      const notionalUsdt = Math.abs(quantityBtc * (markPrice || entryPrice));
      return {
        side: posSide === "short" ? "short" : "long",
        quantityBtc,
        contracts: Math.abs(rawPos),
        entryPrice,
        markPrice,
        notionalUsdt,
        leverage: Number(item.lever || 100),
        marginUsdt: Number(item.margin || item.imr || 0),
        liquidationPrice: Number(item.liqPx || 0),
        uplUsdt: Number(item.upl || 0),
        posSide: item.posSide,
      };
    });
}

function selectActivePosition(parsedPositions) {
  if (!parsedPositions.length) return null;
  return parsedPositions
    .slice()
    .sort((a, b) => (b.marginUsdt || b.notionalUsdt || 0) - (a.marginUsdt || a.notionalUsdt || 0))[0];
}

async function weeklyPerformance(env, equityCny) {
  const key = `week-start:${beijingWeekKey()}`;
  const fallbackLimit = equityCny * weeklyRiskPct(equityCny);
  if (!env.ACCOUNT_KV) {
    return {
      weekStartEquityCny: equityCny,
      weekProfitCny: 0,
      weekLossCny: 0,
      weeklyLossLimitCny: fallbackLimit,
      weekRiskCny: fallbackLimit,
      weeklyRiskStatus: "本周基准未持久化，暂按当前权益估算",
      weeklyStatus: "KV not bound; using current equity as week baseline",
    };
  }
  let baseline = Number(await env.ACCOUNT_KV.get(key));
  if (!Number.isFinite(baseline) || baseline <= 0) {
    baseline = equityCny;
    await env.ACCOUNT_KV.put(key, String(baseline));
  }
  const weekProfitCny = equityCny - baseline;
  const weeklyLossLimitCny = baseline * weeklyRiskPct(baseline);
  const hitLimit = weekProfitCny <= -weeklyLossLimitCny;
  return {
    weekStartEquityCny: baseline,
    weekProfitCny,
    weekLossCny: Math.max(0, baseline - equityCny),
    weeklyLossLimitCny,
    weekRiskCny: weeklyLossLimitCny,
    weeklyRiskStatus: hitLimit ? "本周禁止开新仓，只允许减仓/止损/平仓" : "本周风控正常",
    weeklyStatus: "week baseline synced",
  };
}

function macroDirection(event) {
  const title = `${event.event || ""} ${event.category || ""}`.toLowerCase();
  const actual = Number(event.actual);
  const forecast = Number(event.forecast);
  const previous = Number(event.previous);
  const hasActual = Number.isFinite(actual);
  const hasForecast = Number.isFinite(forecast);
  const hasPrevious = Number.isFinite(previous);
  if (!hasActual) return "待公布：公布前不追单，优先降低100x仓位风险。";
  const compare = hasForecast ? actual - forecast : hasPrevious ? actual - previous : 0;
  const absPct = hasForecast && forecast ? Math.abs(compare / forecast) : 0;
  const close = Math.abs(compare) < 0.01 || absPct < 0.01;
  if (close) return "接近预期：方向中性，优先看技术面、资金费率和支撑阻力。";
  const isInflation = /(cpi|ppi|pce|inflation|average hourly|wage|earnings)/i.test(title);
  const isJobs = /(non farm|payroll|employment|unemployment|jobless|initial claims)/i.test(title);
  const isGrowth = /(gdp|retail|ism|pmi)/i.test(title);
  if (isInflation) return compare > 0 ? "偏利空BTC：通胀或薪资强于预期，可能推高美元和美债收益率。" : "偏利多BTC：通胀或薪资低于预期，降息预期更容易升温。";
  if (isJobs) {
    if (/unemployment|jobless|claims/i.test(title)) {
      return compare > 0 ? "先偏利多BTC：就业降温强化降息预期，但过弱会带来风险资产回落。" : "偏利空BTC：就业仍强，可能压制降息预期。";
    }
    return compare > 0 ? "偏利空BTC：就业强于预期，美元和美债收益率可能走强。" : "偏利多BTC：就业温和降温，流动性预期改善。";
  }
  if (isGrowth) return compare > 0 ? "偏利空BTC：增长强于预期可能压制降息交易。" : "偏利多BTC：增长温和降温更利于宽松预期，过弱则防冲高回落。";
  return compare > 0 ? "数据强于预期：倾向利空BTC，需观察美元和美债反应。" : "数据弱于预期：倾向利多BTC，但需观察风险资产是否承压。";
}

function normalizeMacroEvent(item, now = new Date()) {
  const date = item.Date || item.date || item.dateUtc || item.CalendarId;
  const scheduledAt = date ? new Date(date) : now;
  const actual = item.Actual ?? item.actual ?? "";
  const released = actual !== "" && actual !== null && actual !== undefined;
  return {
    title: item.Event || item.event || item.Category || "宏观事件",
    country: item.Country || item.country || "",
    category: item.Category || item.category || "",
    scheduledAt: scheduledAt.toISOString(),
    impact: item.Importance || item.importance || item.Impact || "中",
    forecast: item.Forecast ?? item.forecast ?? "",
    previous: item.Previous ?? item.previous ?? "",
    actual,
    status: released ? "已公布" : "待公布",
    source: "Trading Economics",
    btcDirection: macroDirection({
      event: item.Event || item.event || "",
      category: item.Category || item.category || "",
      actual,
      forecast: item.Forecast ?? item.forecast ?? "",
      previous: item.Previous ?? item.previous ?? "",
    }),
  };
}

function officialMacroEvents(now) {
  return [
    {
      title: "美国7月CPI通胀数据",
      country: "US",
      category: "Inflation",
      scheduledAt: "2026-08-12T12:30:00.000Z",
      impact: "高",
      forecast: "精确一致预期未接入；市场大致预期温和降温",
      previous: "6月CPI同比3.5%；核心CPI同比2.6%",
      actual: "CPI环比+0.1%、同比+3.4%；核心CPI环比+0.2%、同比+2.5%",
      status: "已公布",
      source: "BLS官方CPI发布",
      btcDirection: "中性偏利多BTC：通胀和核心通胀继续降温，但仍高于长期目标，追多需要看美元和美债是否配合。",
    },
    {
      title: "美国8月CPI通胀数据",
      country: "US",
      category: "Inflation",
      scheduledAt: "2026-09-11T12:30:00.000Z",
      impact: "高",
      forecast: "待公布前更新一致预期",
      previous: "7月CPI同比3.4%；核心CPI同比2.5%",
      actual: "",
      status: "待公布",
      source: "BLS官方CPI日程",
      btcDirection: "待公布：若通胀继续降温偏利多BTC；若重新升温偏利空BTC。",
    },
  ].filter((event) => {
    const t = new Date(event.scheduledAt);
    const until = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    const recentFrom = new Date(now.getTime() - RECENT_MACRO_KEEP_MS);
    return (t >= now && t <= until) || (event.status === "已公布" && t >= recentFrom && t <= now);
  });
}

function dedupeMacroEvents(events) {
  const seen = new Set();
  const deduped = [];
  for (const event of events) {
    const key = `${event.title}|${event.scheduledAt}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(event);
  }
  return deduped.sort((a, b) => new Date(a.scheduledAt) - new Date(b.scheduledAt));
}

async function macroBrief(request, env) {
  const now = new Date();
  const until = new Date(now.getTime() + 24 * 60 * 60 * 1000);
  const recentFrom = new Date(now.getTime() - RECENT_MACRO_KEEP_MS);
  const warnings = [];
  let events = [];
  const sources = [];
  if (env.TRADING_ECONOMICS_KEY) {
    try {
      const url = `${TE_BASE}/calendar?c=${encodeURIComponent(env.TRADING_ECONOMICS_KEY)}&importance=2,3`;
      const response = await fetch(url, { cf: { cacheTtl: 30 } });
      if (!response.ok) throw new Error(`Trading Economics HTTP ${response.status}`);
      const payload = await response.json();
      events = (Array.isArray(payload) ? payload : [])
        .map((item) => normalizeMacroEvent(item, now))
        .filter((event) => {
          const t = new Date(event.scheduledAt);
          return t >= recentFrom && t <= until;
        })
        .slice(0, 12);
      if (events.length) sources.push("trading-economics");
    } catch (error) {
      warnings.push(`Trading Economics 获取失败：${String(error).slice(0, 120)}`);
    }
  } else {
    warnings.push("Trading Economics Key 未配置，精确一致预期/全量实际值源未启用");
  }
  const officialEvents = officialMacroEvents(now);
  if (officialEvents.length) sources.push("official-macro-fallback");
  const combined = dedupeMacroEvents([...events, ...officialEvents]);
  const upcomingEvents = combined.filter((event) => {
    const t = new Date(event.scheduledAt);
    return !event.placeholder && t >= now && t <= until;
  });
  const recentReleasedEvents = combined.filter((event) => {
    const t = new Date(event.scheduledAt);
    return !event.placeholder && event.status === "已公布" && t >= recentFrom && t <= now;
  });
  let visibleEvents = [...upcomingEvents, ...recentReleasedEvents].slice(0, 12);
  if (!visibleEvents.length) {
    visibleEvents = [{
      title: "未来24小时暂无已接入的高影响宏观事件",
      placeholder: true,
      country: "US",
      category: "Macro",
      scheduledAt: now.toISOString(),
      impact: "低",
      forecast: "",
      previous: "",
      actual: "",
      status: "观察",
      source: sources.length ? sources.join("+") : "fallback",
      btcDirection: "宏观窗口暂不提供明确方向，优先看实时技术评分。",
    }];
  }
  return jsonResponse({
    ok: true,
    source: sources.length ? sources.join("+") : "fallback",
    updatedAt: now.toISOString(),
    windowStart: now.toISOString(),
    windowEnd: until.toISOString(),
    events: visibleEvents,
    upcomingEvents,
    recentReleasedEvents,
    warnings,
    macroStatus: {
      tradingEconomicsConfigured: Boolean(env.TRADING_ECONOMICS_KEY),
      officialFallbackActive: true,
      recentKeepHours: RECENT_MACRO_KEEP_MS / (60 * 60 * 1000),
    },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });
    const url = new URL(request.url);
    if (url.pathname === "/macro") return macroBrief(request, env);
    try {
      for (const key of ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"]) {
        if (!env[key]) throw new Error(`Missing ${key}`);
      }
      const workerFetchedAt = new Date().toISOString();
      const [balances, positions, instruments, rateInfo] = await Promise.all([
        okxGet(env, "/api/v5/account/balance?ccy=USDT"),
        okxGet(env, "/api/v5/account/positions?instType=SWAP&instId=BTC-USDT-SWAP"),
        okxGet(env, "/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP"),
        cnyRate(),
      ]);
      const balance = balances[0] || {};
      const detail = (balance.details || []).find((item) => item.ccy === "USDT") || {};
      const equityUsdt = Number(detail.eq || balance.totalEq || 0);
      const availableUsdt = Number(detail.availEq || detail.availBal || 0);
      const equityCny = equityUsdt * rateInfo.rate;
      const week = await weeklyPerformance(env, equityCny);
      const parsedPositions = parsePositions(positions, instruments);
      const activePosition = selectActivePosition(parsedPositions);
      return jsonResponse({
        ok: true,
        source: "cloudflare-worker-okx-private",
        updatedAt: workerFetchedAt,
        workerFetchedAt,
        okxFetchedAt: workerFetchedAt,
        equityUsdt,
        availableUsdt,
        equityCny,
        cnyRate: rateInfo.rate,
        cnyRateSource: rateInfo.source,
        ...week,
        position: activePosition,
        positions: parsedPositions,
        hasHedgedPositions: parsedPositions.length > 1,
      });
    } catch (error) {
      return jsonResponse({ ok: false, error: String(error), updatedAt: new Date().toISOString() }, 500);
    }
  },
};
