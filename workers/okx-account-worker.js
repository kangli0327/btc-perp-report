const OKX_BASE = "https://www.okx.com";
const FALLBACK_CNY_RATE = 7.2;
const TE_BASE = "https://api.tradingeconomics.com";
const RECENT_MACRO_KEEP_MS = 7 * 24 * 60 * 60 * 1000;
const FREE_MACRO_SOURCE = "official-free";
const SIM_KV_KEY = "SIM_ACCOUNT_STATE_V1";
const SIM_INITIAL_CNY = 50000;
const SIM_LEVERAGE = 100;
const SIM_FEE_RATE = 0.0005;
const SIM_MAX_MARGIN_PCT = 0.12;
const SIM_MAX_LOSS_PCT = 0.03;
const SIM_COOLDOWN_MS = 15 * 60 * 1000;
const SIM_PAUSE_AFTER_LOSSES_MS = 2 * 60 * 60 * 1000;
const POLICY_CRYPTO_KEYWORDS = [
  "White House",
  "CFTC",
  "CLARITY Act",
  "Strategic Bitcoin Reserve",
  "Digital Asset Stockpile",
  "crypto regulation",
  "Bitcoin reserve",
];

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
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

async function okxPublic(path, cacheTtl = 5) {
  const response = await fetch(`${OKX_BASE}${path}`, { cf: { cacheTtl } });
  const payload = await response.json();
  if (!response.ok || payload.code !== "0") throw new Error(`OKX public ${path} failed: ${payload.msg || response.status}`);
  return payload.data || [];
}

async function okxPublicOptional(path, fallback = [], cacheTtl = 30) {
  try {
    return await okxPublic(path, cacheTtl);
  } catch {
    return fallback;
  }
}

function okxCandle(row) {
  return {
    ts: Number(row[0]),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5]),
    quoteVolume: Number(row[7] || row[6] || 0),
  };
}

function closes(candles) {
  return (candles || []).map((item) => Number(item.close || 0)).filter((value) => Number.isFinite(value) && value > 0);
}

function emaSeries(values, length) {
  if (!values.length) return [];
  const alpha = 2 / (length + 1);
  const result = [values[0]];
  for (let i = 1; i < values.length; i += 1) result.push(values[i] * alpha + result[result.length - 1] * (1 - alpha));
  return result;
}

function ema(values, length) {
  const series = emaSeries(values, length);
  return series.length ? series[series.length - 1] : 0;
}

function rsi(values, length = 14) {
  if (values.length <= length) return 50;
  let gain = 0;
  let loss = 0;
  const slice = values.slice(-length - 1);
  for (let i = 1; i < slice.length; i += 1) {
    const diff = slice[i] - slice[i - 1];
    if (diff >= 0) gain += diff;
    else loss += Math.abs(diff);
  }
  const avgGain = gain / length;
  const avgLoss = loss / length;
  if (!avgLoss) return avgGain ? 100 : 50;
  return 100 - 100 / (1 + avgGain / avgLoss);
}

function macd(values) {
  if (values.length < 35) return { hist: 0 };
  const fast = emaSeries(values, 12);
  const slow = emaSeries(values, 26);
  const line = fast.map((value, index) => value - slow[index]);
  const signal = emaSeries(line, 9);
  return { hist: (line[line.length - 1] || 0) - (signal[signal.length - 1] || 0) };
}

function atr(candles, length = 14) {
  if (!candles || candles.length < 2) return 0;
  const slice = candles.slice(-length - 1);
  const ranges = [];
  for (let i = 1; i < slice.length; i += 1) {
    const current = slice[i];
    const prev = slice[i - 1];
    ranges.push(Math.max(current.high - current.low, Math.abs(current.high - prev.close), Math.abs(current.low - prev.close)));
  }
  return ranges.length ? ranges.reduce((a, b) => a + b, 0) / ranges.length : 0;
}

function volumeRatio(candles, length = 20) {
  if (!candles || candles.length < 2) return 1;
  const previous = candles.slice(0, -1).slice(-length);
  const base = previous.reduce((sum, item) => sum + Number(item.quoteVolume || item.volume || 0), 0) / Math.max(previous.length, 1);
  return base ? Number(candles[candles.length - 1].quoteVolume || candles[candles.length - 1].volume || 0) / base : 1;
}

function vwap(candles) {
  let numerator = 0;
  let denominator = 0;
  (candles || []).forEach((item) => {
    const volume = Number(item.quoteVolume || item.volume || 0);
    const typical = (item.high + item.low + item.close) / 3;
    numerator += typical * volume;
    denominator += volume;
  });
  return denominator ? numerator / denominator : 0;
}

function emaState(candles) {
  const values = closes(candles);
  const latest = values[values.length - 1] || 0;
  const e20 = ema(values, 20);
  const e60 = ema(values, 60);
  const e120 = ema(values, 120);
  if (latest > e20 && e20 > e60 && e60 > e120) return "EMA多头排列";
  if (latest < e20 && e20 < e60 && e60 < e120) return "EMA空头排列";
  if (latest > e20 && e20 > e60) return "EMA偏多";
  if (latest < e20 && e20 < e60) return "EMA偏空";
  return "EMA震荡";
}

function higherLows(candles, count = 3) {
  const slice = (candles || []).slice(-count);
  return slice.length >= count && slice.every((item, index) => index === 0 || item.low > slice[index - 1].low);
}

function lowerHighs(candles, count = 3) {
  const slice = (candles || []).slice(-count);
  return slice.length >= count && slice.every((item, index) => index === 0 || item.high < slice[index - 1].high);
}

async function simMarketSnapshot() {
  const [markData, c15Rows, c1hRows, c4hRows, c5Rows, fundingRows, rateInfo] = await Promise.all([
    okxPublic("/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP", 2),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=160", 10),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1H&limit=160", 30),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=4H&limit=160", 60),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=5m&limit=80", 10),
    okxPublicOptional("/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", [{ fundingRate: 0 }], 120),
    cnyRate(),
  ]);
  const c15 = c15Rows.map(okxCandle).reverse();
  const c1h = c1hRows.map(okxCandle).reverse();
  const c4h = c4hRows.map(okxCandle).reverse();
  const c5m = c5Rows.map(okxCandle).reverse();
  const latest = Number(markData[0]?.markPx || c15[c15.length - 1]?.close || 0);
  const closes15 = closes(c15);
  const closes1h = closes(c1h);
  const closes4h = closes(c4h);
  const recent24h = c15.slice(-96);
  const supportWindow = c15.slice(-24);
  const support = supportWindow.length ? Math.min(...supportWindow.map((item) => item.low || latest)) : latest * 0.995;
  const resistance = supportWindow.length ? Math.max(...supportWindow.map((item) => item.high || latest)) : latest * 1.005;
  const vwap24h = vwap(recent24h);
  const atr15m = atr(c15);
  const funding = Number(fundingRows[0]?.fundingRate || 0) * 100;
  const metrics = {
    latest,
    support,
    resistance,
    rsi15m: rsi(closes15),
    rsi1h: rsi(closes1h),
    rsi4h: rsi(closes4h),
    macd15m: macd(closes15),
    macd1h: macd(closes1h),
    macd4h: macd(closes4h),
    ema4h: emaState(c4h),
    volumeRatio15m: volumeRatio(c15),
    volumeRatio1h: volumeRatio(c1h),
    atr15m,
    vwap24h,
    priceVsVwapPct: vwap24h ? (latest / vwap24h - 1) * 100 : 0,
    funding,
    higherLows5m: higherLows(c5m),
    lowerHighs5m: lowerHighs(c5m),
  };
  return { metrics, rateInfo, updatedAt: new Date().toISOString() };
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

function beijingTimeText(value = new Date()) {
  return new Date(value).toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function emptySimState(now = new Date()) {
  return {
    version: 1,
    createdAt: now.toISOString(),
    updatedAt: now.toISOString(),
    balanceCny: SIM_INITIAL_CNY,
    initialCny: SIM_INITIAL_CNY,
    maxEquityCny: SIM_INITIAL_CNY,
    position: null,
    records: [],
    totalTrades: 0,
    winTrades: 0,
    lossStreak: 0,
    pauseUntil: null,
    lastDecisionAt: null,
    lastOpenSide: null,
  };
}

async function readSimState(env) {
  if (!env.ACCOUNT_KV) return emptySimState();
  const raw = await env.ACCOUNT_KV.get(SIM_KV_KEY);
  if (!raw) return emptySimState();
  try {
    return { ...emptySimState(), ...JSON.parse(raw) };
  } catch {
    return emptySimState();
  }
}

async function writeSimState(env, state) {
  if (!env.ACCOUNT_KV) return;
  await env.ACCOUNT_KV.put(SIM_KV_KEY, JSON.stringify(state));
}

function simPnlCny(position, latest, rate) {
  if (!position) return 0;
  const rawUsdt = position.side === "long"
    ? (latest - position.entryPrice) * position.quantityBtc
    : (position.entryPrice - latest) * position.quantityBtc;
  return rawUsdt * rate;
}

function pushSimRecord(state, record) {
  const now = new Date();
  state.records = [
    {
      id: `${now.getTime()}-${Math.random().toString(16).slice(2, 8)}`,
      createdAt: now.toISOString(),
      time: beijingTimeText(now),
      ...record,
    },
    ...(state.records || []),
  ].slice(0, 100);
}

function simScores(metrics) {
  let longScore = 35;
  let shortScore = 35;
  let riskScore = 20;
  if (metrics.rsi4h > 55) longScore += 14;
  else if (metrics.rsi4h < 45) shortScore += 14;
  if (metrics.macd1h.hist > 0) longScore += 16;
  else if (metrics.macd1h.hist < 0) shortScore += 16;
  if (metrics.macd15m.hist > 0 && metrics.volumeRatio15m > 1.15) longScore += 10;
  if (metrics.macd15m.hist < 0 && metrics.volumeRatio15m > 1.15) shortScore += 10;
  if (["EMA多头排列", "EMA偏多"].includes(metrics.ema4h)) longScore += 12;
  if (["EMA空头排列", "EMA偏空"].includes(metrics.ema4h)) shortScore += 12;
  if (metrics.priceVsVwapPct > 0.2) longScore += 7;
  if (metrics.priceVsVwapPct < -0.2) shortScore += 7;
  if (metrics.funding > 0.02 && metrics.macd1h.hist < 0) shortScore += 7;
  if (metrics.funding < -0.02 && metrics.macd1h.hist > 0) longScore += 7;
  if (metrics.atr15m && metrics.latest && metrics.atr15m / metrics.latest * 100 > 0.6) riskScore += 20;
  if (Math.abs(longScore - shortScore) < 12) riskScore += 15;
  let longWarningScore = 25;
  let shortWarningScore = 25;
  if (metrics.higherLows5m) longWarningScore += 22;
  if (metrics.lowerHighs5m) shortWarningScore += 22;
  if (metrics.latest > metrics.vwap24h && metrics.macd15m.hist > 0) longWarningScore += 24;
  if (metrics.latest < metrics.vwap24h && metrics.macd15m.hist < 0) shortWarningScore += 24;
  if (metrics.latest > metrics.resistance - metrics.atr15m * 0.25) longWarningScore += 10;
  if (metrics.latest < metrics.support + metrics.atr15m * 0.25) shortWarningScore += 10;
  return {
    longScore: Math.max(0, Math.min(100, Math.round(longScore))),
    shortScore: Math.max(0, Math.min(100, Math.round(shortScore))),
    riskScore: Math.max(0, Math.min(100, Math.round(riskScore))),
    longWarningScore: Math.max(0, Math.min(100, Math.round(longWarningScore))),
    shortWarningScore: Math.max(0, Math.min(100, Math.round(shortWarningScore))),
  };
}

function closeSimPosition(state, market, action, reason) {
  const position = state.position;
  if (!position) return 0;
  const latest = market.metrics.latest;
  const rate = market.rateInfo.rate;
  const pnlCny = simPnlCny(position, latest, rate);
  const closeFeeCny = position.notionalUsdt * SIM_FEE_RATE * rate;
  const netPnlCny = pnlCny - closeFeeCny;
  state.balanceCny += netPnlCny;
  state.totalTrades += 1;
  if (netPnlCny > 0) {
    state.winTrades += 1;
    state.lossStreak = 0;
  } else {
    state.lossStreak += 1;
    if (state.lossStreak >= 3) state.pauseUntil = new Date(Date.now() + SIM_PAUSE_AFTER_LOSSES_MS).toISOString();
  }
  pushSimRecord(state, {
    action,
    side: position.side,
    price: latest,
    quantityBtc: position.quantityBtc,
    marginCny: position.marginCny,
    feeCny: closeFeeCny,
    pnlCny: netPnlCny,
    balanceCny: state.balanceCny,
    reason,
  });
  state.position = null;
  return netPnlCny;
}

function openSimPosition(state, market, side, reason) {
  const latest = market.metrics.latest;
  const rate = market.rateInfo.rate;
  const equityCny = state.balanceCny;
  const riskDistance = Math.max(market.metrics.atr15m * 1.2, latest * 0.004);
  const maxMarginCny = equityCny * SIM_MAX_MARGIN_PCT;
  const maxRiskUsdt = equityCny * SIM_MAX_LOSS_PCT / rate;
  const qtyByRisk = maxRiskUsdt / riskDistance;
  const qtyByMargin = (maxMarginCny / rate * SIM_LEVERAGE) / latest;
  const quantityBtc = Math.max(0, Math.min(qtyByRisk, qtyByMargin));
  const notionalUsdt = quantityBtc * latest;
  const marginUsdt = notionalUsdt / SIM_LEVERAGE;
  const marginCny = marginUsdt * rate;
  const feeCny = notionalUsdt * SIM_FEE_RATE * rate;
  const stopLoss = side === "long" ? latest - riskDistance : latest + riskDistance;
  const takeProfit = side === "long" ? latest + riskDistance * 1.8 : latest - riskDistance * 1.8;
  state.balanceCny -= feeCny;
  state.position = {
    side,
    entryPrice: latest,
    quantityBtc,
    marginCny,
    marginUsdt,
    notionalUsdt,
    leverage: SIM_LEVERAGE,
    takeProfit,
    stopLoss,
    openedAt: new Date().toISOString(),
    reason,
  };
  state.lastDecisionAt = new Date().toISOString();
  state.lastOpenSide = side;
  pushSimRecord(state, {
    action: side === "long" ? "开多" : "开空",
    side,
    price: latest,
    quantityBtc,
    marginCny,
    feeCny,
    pnlCny: -feeCny,
    balanceCny: state.balanceCny,
    reason,
  });
}

function canOpenSim(state, scores, side) {
  const now = Date.now();
  if (state.pauseUntil && new Date(state.pauseUntil).getTime() > now) return "连续亏损3笔，暂停开仓2小时。";
  if (state.balanceCny < SIM_INITIAL_CNY * 0.7) return "模拟权益低于初始资金70%，进入冷静模式，只允许平仓。";
  if (scores.riskScore >= 80) return "风险评分过高，禁止开新仓。";
  if (state.lastDecisionAt && state.lastOpenSide === side && now - new Date(state.lastDecisionAt).getTime() < SIM_COOLDOWN_MS) return "同方向开仓冷却中，避免页面刷新造成过度交易。";
  return "";
}

function runSimDecision(state, market) {
  const metrics = market.metrics;
  const scores = simScores(metrics);
  const rate = market.rateInfo.rate;
  let decision = "观望";
  let reason = "多空确认分和预警分未形成同向优势，继续等待。";
  if (state.position) {
    const position = state.position;
    if ((position.side === "long" && metrics.latest <= position.stopLoss) || (position.side === "short" && metrics.latest >= position.stopLoss)) {
      closeSimPosition(state, market, "止损平仓", "价格触及开仓时锁定止损，优先控制单笔亏损。");
      decision = "止损平仓";
      reason = "价格触及开仓时锁定止损。";
    } else if ((position.side === "long" && metrics.latest >= position.takeProfit) || (position.side === "short" && metrics.latest <= position.takeProfit)) {
      closeSimPosition(state, market, "止盈平仓", "价格触及开仓时锁定止盈，落袋为安。");
      decision = "止盈平仓";
      reason = "价格触及开仓时锁定止盈。";
    } else if (position.side === "long" && scores.shortScore - scores.longScore >= 22 && scores.shortWarningScore >= 65) {
      closeSimPosition(state, market, "反向信号平仓", "空头评分和预警明显反向，先退出多单。");
      decision = "反向信号平仓";
      reason = "空头评分和预警明显反向。";
    } else if (position.side === "short" && scores.longScore - scores.shortScore >= 22 && scores.longWarningScore >= 65) {
      closeSimPosition(state, market, "反向信号平仓", "多头评分和预警明显反向，先退出空单。");
      decision = "反向信号平仓";
      reason = "多头评分和预警明显反向。";
    } else {
      decision = "持仓";
      reason = "已有仓位未触及止盈止损，原计划继续执行。";
    }
  }
  if (!state.position && !["止损平仓", "止盈平仓", "反向信号平仓"].includes(decision)) {
    const longReady = scores.longScore >= 64 && scores.longWarningScore >= 64 && scores.longScore - scores.shortScore >= 12;
    const shortReady = scores.shortScore >= 64 && scores.shortWarningScore >= 64 && scores.shortScore - scores.longScore >= 12;
    if (longReady) {
      const blockReason = canOpenSim(state, scores, "long");
      if (blockReason) {
        decision = "风控禁止开仓";
        reason = blockReason;
      } else {
        reason = "多头确认分和预警分同向，价格站上VWAP且短线结构偏强，开多试仓。";
        openSimPosition(state, market, "long", reason);
        decision = "开多";
      }
    } else if (shortReady) {
      const blockReason = canOpenSim(state, scores, "short");
      if (blockReason) {
        decision = "风控禁止开仓";
        reason = blockReason;
      } else {
        reason = "空头确认分和预警分同向，价格跌破VWAP且1小时MACD偏弱，开空试仓。";
        openSimPosition(state, market, "short", reason);
        decision = "开空";
      }
    }
  }
  if (["观望", "风控禁止开仓"].includes(decision)) {
    const latestRecord = (state.records || [])[0];
    const shouldLog = !latestRecord
      || latestRecord.action !== decision
      || Date.now() - new Date(latestRecord.createdAt || 0).getTime() > SIM_COOLDOWN_MS;
    if (shouldLog) {
      pushSimRecord(state, {
        action: decision,
        side: state.position?.side || "flat",
        price: metrics.latest,
        quantityBtc: state.position?.quantityBtc || 0,
        marginCny: state.position?.marginCny || 0,
        feeCny: 0,
        pnlCny: 0,
        balanceCny: state.balanceCny,
        reason,
      });
    }
  }
  const floatingPnlCny = simPnlCny(state.position, metrics.latest, rate);
  const equityCny = state.balanceCny + floatingPnlCny;
  state.maxEquityCny = Math.max(Number(state.maxEquityCny || SIM_INITIAL_CNY), equityCny);
  state.updatedAt = new Date().toISOString();
  return {
    decision,
    reason,
    scores,
    floatingPnlCny,
    equityCny,
    drawdownPct: state.maxEquityCny ? (equityCny / state.maxEquityCny - 1) * 100 : 0,
    winRate: state.totalTrades ? state.winTrades / state.totalTrades * 100 : 0,
  };
}

async function simBrief(request, env) {
  try {
    if (!env.ACCOUNT_KV) return jsonResponse({ ok: false, error: "ACCOUNT_KV 未绑定，模拟盘无法保存状态" }, 500);
    if (request.method === "POST" && new URL(request.url).pathname === "/sim/reset") {
      const state = emptySimState();
      pushSimRecord(state, { action: "重置模拟盘", side: "flat", price: 0, quantityBtc: 0, marginCny: 0, feeCny: 0, pnlCny: 0, balanceCny: state.balanceCny, reason: "手动重置为初始本金¥50,000。" });
      await writeSimState(env, state);
      return jsonResponse({ ok: true, reset: true, state });
    }
    const [state, market] = await Promise.all([readSimState(env), simMarketSnapshot()]);
    const result = runSimDecision(state, market);
    await writeSimState(env, state);
    return jsonResponse({
      ok: true,
      source: "ai-sim-worker",
      updatedAt: state.updatedAt,
      balanceCny: state.balanceCny,
      equityCny: result.equityCny,
      floatingPnlCny: result.floatingPnlCny,
      initialCny: state.initialCny,
      maxEquityCny: state.maxEquityCny,
      drawdownPct: result.drawdownPct,
      winRate: result.winRate,
      totalTrades: state.totalTrades,
      winTrades: state.winTrades,
      lossStreak: state.lossStreak,
      pauseUntil: state.pauseUntil,
      decision: result.decision,
      decisionReason: result.reason,
      scores: result.scores,
      position: state.position,
      records: (state.records || []).slice(0, 100),
      market: {
        latest: market.metrics.latest,
        cnyRate: market.rateInfo.rate,
        cnyRateSource: market.rateInfo.source,
        funding: market.metrics.funding,
        support: market.metrics.support,
        resistance: market.metrics.resistance,
        vwap24h: market.metrics.vwap24h,
      },
      riskRules: {
        maxMarginPct: SIM_MAX_MARGIN_PCT,
        maxLossPct: SIM_MAX_LOSS_PCT,
        leverage: SIM_LEVERAGE,
        feeRate: SIM_FEE_RATE,
        cooldownMinutes: SIM_COOLDOWN_MS / 60000,
      },
    });
  } catch (error) {
    return jsonResponse({ ok: false, error: String(error), updatedAt: new Date().toISOString(), source: "ai-sim-worker" }, 500);
  }
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
      type: "经济数据",
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
      type: "经济数据",
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

function policyCryptoEvents(now) {
  return [
    {
      title: "白宫加密会议推动CLARITY Act与美国比特币储备叙事",
      country: "US",
      category: "Crypto Policy",
      type: "加密政策",
      scheduledAt: "2026-08-19T16:00:00.000Z",
      impact: "高",
      forecast: "政策预期：美国继续推动加密市场监管清晰化，并维持比特币储备叙事热度",
      previous: "此前已建立Strategic Bitcoin Reserve与United States Digital Asset Stockpile政策框架",
      actual: "特朗普在白宫加密活动中推动国会推进CLARITY Act，并强化美国潜在比特币积累与数字资产储备讨论",
      status: "已公布",
      source: "CoinDesk / CFTC / White House",
      sourceUrls: [
        "https://www.coindesk.com/policy/2026/08/19/trump-pushes-congress-to-move-on-clarity-act-during-white-house-crypto-event",
        "https://www.cftc.gov/PressRoom/SpeechesTestimony/opaselig9",
        "https://www.whitehouse.gov/presidential-actions/2025/03/establishment-of-the-strategic-bitcoin-reserve-and-united-states-digital-asset-stockpile/",
      ],
      keywords: POLICY_CRYPTO_KEYWORDS,
      btcDirection: "先利多后防回落：政策面强化美国比特币储备和监管清晰化叙事，利好中期风险偏好；短线若价格已提前反应，需要防兑现回落。",
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
    warnings.push("当前使用免费官方源；精确一致预期和全量实际值覆盖有限");
  }
  const officialEvents = officialMacroEvents(now);
  const cryptoPolicyEvents = policyCryptoEvents(now);
  if (officialEvents.length || cryptoPolicyEvents.length) sources.push(FREE_MACRO_SOURCE);
  const combined = dedupeMacroEvents([...events, ...officialEvents, ...cryptoPolicyEvents]);
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
      source: sources.length ? sources.join("+") : FREE_MACRO_SOURCE,
      btcDirection: "宏观窗口暂不提供明确方向，优先看实时技术评分。",
    }];
  }
  return jsonResponse({
    ok: true,
    source: sources.length ? sources.join("+") : FREE_MACRO_SOURCE,
    updatedAt: now.toISOString(),
    windowStart: now.toISOString(),
    windowEnd: until.toISOString(),
    events: visibleEvents,
    upcomingEvents,
    recentReleasedEvents,
    policyCryptoEvents: cryptoPolicyEvents,
    warnings,
    macroStatus: {
      tradingEconomicsConfigured: Boolean(env.TRADING_ECONOMICS_KEY),
      officialFallbackActive: true,
      freeOfficialMode: !env.TRADING_ECONOMICS_KEY,
      recentKeepHours: RECENT_MACRO_KEEP_MS / (60 * 60 * 1000),
      policyCryptoKeywords: POLICY_CRYPTO_KEYWORDS,
    },
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });
    const url = new URL(request.url);
    if (url.pathname === "/macro") return macroBrief(request, env);
    if (url.pathname === "/sim" || url.pathname === "/sim/reset") return simBrief(request, env);
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
