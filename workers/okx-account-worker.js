const OKX_BASE = "https://www.okx.com";
const BYBIT_BASE = "https://api.bybit.com";
const BINANCE_FAPI_BASE = "https://fapi.binance.com";
const FALLBACK_CNY_RATE = 7.2;
const TE_BASE = "https://api.tradingeconomics.com";
const UPCOMING_MACRO_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;
const RECENT_MACRO_KEEP_MS = 7 * 24 * 60 * 60 * 1000;
const FREE_MACRO_SOURCE = "official-free";
const SIM_KV_KEY = "SIM_ACCOUNT_STATE_V1";
const MACRO_OBS_KV_KEY = "MACRO_OBSERVATION_SNAPSHOT_V1";
const SIM_INITIAL_CNY = 50000;
const SIM_TARGET_CNY = 100000;
const SIM_SPRINT_DAYS = 7;
const SIM_BASE_LEVERAGE = 35;
const SIM_STRONG_LEVERAGE = 60;
const SIM_MAX_LEVERAGE = 100;
const SIM_FEE_RATE = 0.0005;
const SIM_BASE_MARGIN_PCT = 0.18;
const SIM_MAX_MARGIN_PCT = 0.35;
const SIM_BASE_LOSS_PCT = 0.04;
const SIM_MAX_LOSS_PCT = 0.08;
const SIM_BLOWUP_RESTART_CNY = 500;
const SIM_COOLDOWN_MS = 5 * 60 * 1000;
const SIM_TP1_CLOSE_PCT = 0.25;
const SIM_TP2_CLOSE_PCT = 0.25;
const SIM_EXIT_PROFILES = {
  full_tp1: { label: "震荡快出：第一止盈全平", tp1Pct: 1, tp2Pct: 0, useRunner: false },
  tp1_heavy: { label: "混沌保护：第一止盈重仓落袋", tp1Pct: 0.8, tp2Pct: 0.2, useRunner: false },
  partial_runner: { label: "趋势分批：减仓后保留尾仓", tp1Pct: 0.3, tp2Pct: 0.3, useRunner: true },
  breakout_runner: { label: "突破奔跑：轻减仓追踪延伸", tp1Pct: 0.25, tp2Pct: 0.25, useRunner: true },
};
const SIM_MIN_CONFIRM_SCORE = 68;
const SIM_MIN_WARNING_SCORE = 58;
const SIM_MIN_SCORE_EDGE = 16;
const SIM_MAX_VWAP_CHASE_PCT = 0.65;
const SIM_MIN_EXPECTED_RR = 1.35;
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

function binanceCandle(row) {
  return {
    ts: Number(row[0]),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5]),
    quoteVolume: Number(row[7] || 0),
  };
}

function bybitCandle(row) {
  return {
    ts: Number(row[0]),
    open: Number(row[1]),
    high: Number(row[2]),
    low: Number(row[3]),
    close: Number(row[4]),
    volume: Number(row[5]),
    quoteVolume: Number(row[6] || 0),
  };
}

async function bybitPublic(path, cacheTtl = 10) {
  const response = await fetch(`${BYBIT_BASE}${path}`, { cf: { cacheTtl } });
  const payload = await response.json();
  if (!response.ok || payload.retCode !== 0) throw new Error(`Bybit public ${path} failed: ${payload.retMsg || response.status}`);
  return payload.result || {};
}

async function binancePublic(path, cacheTtl = 10) {
  const response = await fetch(`${BINANCE_FAPI_BASE}${path}`, { cf: { cacheTtl } });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error(`Binance public ${path} returned non-JSON`);
  }
  if (!response.ok) throw new Error(`Binance public ${path} failed: ${payload.msg || response.status}`);
  return payload;
}

async function fetchJsonOptional(url, fallback = null, cacheTtl = 120, timeoutMs = 6000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "btc-perp-report/1.0" },
      cf: { cacheTtl },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } catch {
    return fallback;
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchTextOptional(url, fallback = "", cacheTtl = 300, timeoutMs = 6000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: { "User-Agent": "btc-perp-report/1.0" },
      cf: { cacheTtl },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } catch {
    return fallback;
  } finally {
    clearTimeout(timeout);
  }
}

function numberOrNull(value) {
  const number = Number(String(value ?? "").replace(/[$,%\s,]/g, ""));
  return Number.isFinite(number) ? number : null;
}

function closes(candles) {
  return (candles || []).map((item) => Number(item.close || 0)).filter((value) => Number.isFinite(value) && value > 0);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
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

function emaSnapshot(candles) {
  const values = closes(candles);
  const latest = values[values.length - 1] || 0;
  const e20Series = emaSeries(values, 20);
  const e60Series = emaSeries(values, 60);
  const e120Series = emaSeries(values, 120);
  const e20 = e20Series[e20Series.length - 1] || 0;
  const e60 = e60Series[e60Series.length - 1] || 0;
  const e120 = e120Series[e120Series.length - 1] || 0;
  const prev20 = e20Series[e20Series.length - 6] || e20;
  const slope20Pct = latest ? (e20 / prev20 - 1) * 100 : 0;
  return { e20, e60, e120, slope20Pct };
}

function higherLows(candles, count = 3) {
  const slice = (candles || []).slice(-count);
  return slice.length >= count && slice.every((item, index) => index === 0 || item.low > slice[index - 1].low);
}

function lowerHighs(candles, count = 3) {
  const slice = (candles || []).slice(-count);
  return slice.length >= count && slice.every((item, index) => index === 0 || item.high < slice[index - 1].high);
}

function candleChangePct(candles, count = 3) {
  const slice = (candles || []).slice(-count - 1);
  const first = Number(slice[0]?.close || 0);
  const last = Number(slice[slice.length - 1]?.close || 0);
  return first ? (last / first - 1) * 100 : 0;
}

function buildSimMetrics(c15, c1h, c4h, c5m, c1m, latest, funding, rateInfo, source) {
  const closes15 = closes(c15);
  const closes1h = closes(c1h);
  const closes4h = closes(c4h);
  const closes5m = closes(c5m);
  const closes1m = closes(c1m);
  const recent24h = c15.slice(-96);
  const supportWindow = c15.slice(-24);
  const support = supportWindow.length ? Math.min(...supportWindow.map((item) => item.low || latest)) : latest * 0.995;
  const resistance = supportWindow.length ? Math.max(...supportWindow.map((item) => item.high || latest)) : latest * 1.005;
  const vwap24h = vwap(recent24h);
  const atr15m = atr(c15);
  const ema15m = emaSnapshot(c15);
  const ema1h = emaSnapshot(c1h);
  const ema4hSnapshot = emaSnapshot(c4h);
  const previous15 = c15[c15.length - 2] || null;
  const metrics = {
    latest,
    support,
    resistance,
    rsi15m: rsi(closes15),
    rsi1h: rsi(closes1h),
    rsi4h: rsi(closes4h),
    rsi5m: rsi(closes5m),
    rsi1m: rsi(closes1m),
    macd15m: macd(closes15),
    macd1h: macd(closes1h),
    macd4h: macd(closes4h),
    macd5m: macd(closes5m),
    ema4h: emaState(c4h),
    ema15m,
    ema1h,
    ema4hSnapshot,
    volumeRatio15m: volumeRatio(c15),
    volumeRatio5m: volumeRatio(c5m),
    volumeRatio1m: volumeRatio(c1m),
    volumeRatio1h: volumeRatio(c1h),
    atr15m,
    atrPct: latest ? atr15m / latest * 100 : 0,
    vwap24h,
    priceVsVwapPct: vwap24h ? (latest / vwap24h - 1) * 100 : 0,
    rangePct: latest ? (resistance - support) / latest * 100 : 0,
    previous15High: previous15?.high || 0,
    previous15Low: previous15?.low || 0,
    funding,
    change1mPct: candleChangePct(c1m, 3),
    change5mPct: candleChangePct(c5m, 3),
    higherLows5m: higherLows(c5m),
    lowerHighs5m: lowerHighs(c5m),
    higherLows1m: higherLows(c1m),
    lowerHighs1m: lowerHighs(c1m),
    recent1mCandles: (c1m || []).slice(-500).map((item) => ({
      ts: item.ts,
      high: item.high,
      low: item.low,
      close: item.close,
    })),
  };
  return { metrics, rateInfo, source, updatedAt: new Date().toISOString() };
}

async function okxSimMarketSnapshot() {
  const [markData, c15Rows, c1hRows, c4hRows, c5Rows, c1Rows, fundingRows, rateInfo] = await Promise.all([
    okxPublic("/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP", 2),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=160", 10),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1H&limit=160", 30),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=4H&limit=160", 60),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=5m&limit=80", 10),
    okxPublic("/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1m&limit=300", 10),
    okxPublicOptional("/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", [{ fundingRate: 0 }], 120),
    cnyRate(),
  ]);
  const c15 = c15Rows.map(okxCandle).reverse();
  const c1h = c1hRows.map(okxCandle).reverse();
  const c4h = c4hRows.map(okxCandle).reverse();
  const c5m = c5Rows.map(okxCandle).reverse();
  const c1m = c1Rows.map(okxCandle).reverse();
  const latest = Number(markData[0]?.markPx || c15[c15.length - 1]?.close || 0);
  const funding = Number(fundingRows[0]?.fundingRate || 0) * 100;
  return buildSimMetrics(c15, c1h, c4h, c5m, c1m, latest, funding, rateInfo, "OKX公共行情");
}

async function binanceSimMarketSnapshot() {
  const [premium, c15Rows, c1hRows, c4hRows, c5Rows, c1Rows, rateInfo] = await Promise.all([
    binancePublic("/fapi/v1/premiumIndex?symbol=BTCUSDT", 2),
    binancePublic("/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=160", 10),
    binancePublic("/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=160", 30),
    binancePublic("/fapi/v1/klines?symbol=BTCUSDT&interval=4h&limit=160", 60),
    binancePublic("/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=80", 10),
    binancePublic("/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=500", 10),
    cnyRate(),
  ]);
  const c15 = c15Rows.map(binanceCandle);
  const c1h = c1hRows.map(binanceCandle);
  const c4h = c4hRows.map(binanceCandle);
  const c5m = c5Rows.map(binanceCandle);
  const c1m = c1Rows.map(binanceCandle);
  const latest = Number(premium.markPrice || c15[c15.length - 1]?.close || 0);
  const funding = Number(premium.lastFundingRate || 0) * 100;
  return buildSimMetrics(c15, c1h, c4h, c5m, c1m, latest, funding, rateInfo, "Binance USD-M备用行情");
}

async function bybitSimMarketSnapshot() {
  const [ticker, c15Data, c1hData, c4hData, c5Data, c1Data, rateInfo] = await Promise.all([
    bybitPublic("/v5/market/tickers?category=linear&symbol=BTCUSDT", 2),
    bybitPublic("/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15&limit=160", 10),
    bybitPublic("/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=160", 30),
    bybitPublic("/v5/market/kline?category=linear&symbol=BTCUSDT&interval=240&limit=160", 60),
    bybitPublic("/v5/market/kline?category=linear&symbol=BTCUSDT&interval=5&limit=80", 10),
    bybitPublic("/v5/market/kline?category=linear&symbol=BTCUSDT&interval=1&limit=500", 10),
    cnyRate(),
  ]);
  const c15 = (c15Data.list || []).map(bybitCandle).reverse();
  const c1h = (c1hData.list || []).map(bybitCandle).reverse();
  const c4h = (c4hData.list || []).map(bybitCandle).reverse();
  const c5m = (c5Data.list || []).map(bybitCandle).reverse();
  const c1m = (c1Data.list || []).map(bybitCandle).reverse();
  const item = (ticker.list || [])[0] || {};
  const latest = Number(item.markPrice || item.lastPrice || c15[c15.length - 1]?.close || 0);
  const funding = Number(item.fundingRate || 0) * 100;
  return buildSimMetrics(c15, c1h, c4h, c5m, c1m, latest, funding, rateInfo, "Bybit线性合约备用行情");
}

async function simMarketSnapshot() {
  try {
    return await okxSimMarketSnapshot();
  } catch (okxError) {
    try {
      const fallback = await bybitSimMarketSnapshot();
      return { ...fallback, sourceWarning: `OKX公共行情失败，已切换Bybit备用：${String(okxError).slice(0, 100)}` };
    } catch (bybitError) {
      const fallback = await binanceSimMarketSnapshot();
      return { ...fallback, sourceWarning: `OKX/Bybit公共行情失败，已切换Binance备用：${String(bybitError).slice(0, 100)}` };
    }
  }
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
    resetCount: 0,
    sprintTargetCny: SIM_TARGET_CNY,
    sprintDays: SIM_SPRINT_DAYS,
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
  if (metrics.change1mPct > 0.08 && metrics.volumeRatio1m > 1.25) longWarningScore += 14;
  if (metrics.change1mPct < -0.08 && metrics.volumeRatio1m > 1.25) shortWarningScore += 14;
  if (metrics.change5mPct > 0.16 && metrics.volumeRatio5m > 1.15) longWarningScore += 10;
  if (metrics.change5mPct < -0.16 && metrics.volumeRatio5m > 1.15) shortWarningScore += 10;
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

function simRangePosition(metrics) {
  const support = Number(metrics.support || 0);
  const resistance = Number(metrics.resistance || 0);
  const latest = Number(metrics.latest || 0);
  const width = resistance - support;
  if (!latest || width <= 0) return 0.5;
  return clamp((latest - support) / width, 0, 1);
}

function classifyMarketRegime(metrics, scores) {
  const latest = Number(metrics.latest || 0);
  const ema15 = metrics.ema15m || {};
  const ema1h = metrics.ema1h || {};
  const ema4h = metrics.ema4hSnapshot || {};
  const longStructure = latest > Number(ema15.e20 || 0)
    && Number(ema15.e20 || 0) >= Number(ema15.e60 || 0)
    && latest > Number(ema1h.e20 || 0)
    && Number(ema4h.slope20Pct || 0) >= 0;
  const shortStructure = latest < Number(ema15.e20 || 0)
    && Number(ema15.e20 || 0) <= Number(ema15.e60 || 0)
    && latest < Number(ema1h.e20 || 0)
    && Number(ema4h.slope20Pct || 0) <= 0;
  const scoreEdge = Number(scores.longScore || 0) - Number(scores.shortScore || 0);
  const rangePos = simRangePosition(metrics);
  const nearMiddle = rangePos > 0.32 && rangePos < 0.68;
  const lowTrendEdge = Math.abs(scoreEdge) < 12;
  const controlledAtr = Number(metrics.atrPct || 0) <= 0.85;
  if (longStructure && scoreEdge >= 8 && controlledAtr) {
    return { code: "trend_up", label: "上升趋势", reason: "EMA结构向上，价格在VWAP上方，多头占优。" };
  }
  if (shortStructure && scoreEdge <= -8 && controlledAtr) {
    return { code: "trend_down", label: "下降趋势", reason: "EMA结构向下，价格在VWAP下方，空头占优。" };
  }
  if (latest > Number(metrics.vwap24h || 0) && Number(metrics.change1mPct || 0) > 0.10 && Number(metrics.volumeRatio1m || 0) >= 1.3) {
    return { code: "momentum_up", label: "短线动量向上", reason: "1分钟放量上冲且站在VWAP上方，进入冲刺试多观察。" };
  }
  if (latest < Number(metrics.vwap24h || Infinity) && Number(metrics.change1mPct || 0) < -0.10 && Number(metrics.volumeRatio1m || 0) >= 1.3) {
    return { code: "momentum_down", label: "短线动量向下", reason: "1分钟放量下杀且跌在VWAP下方，进入冲刺试空观察。" };
  }
  if (Number(metrics.rangePct || 0) >= 0.55 && lowTrendEdge && controlledAtr) {
    return {
      code: "range",
      label: "震荡区间",
      reason: nearMiddle ? "价格在区间中部，追单优势不明显。" : "价格靠近区间边缘，可以只看反转模型。",
    };
  }
  return { code: "chop", label: "混沌行情", reason: "趋势、动能和位置没有形成统一优势。" };
}

function simSetupCandidate(metrics, regime, side, setupType, invalidPrice, targetPrices, reason, scores) {
  const latest = Number(metrics.latest || 0);
  const stop = Number(invalidPrice || 0);
  const targets = (targetPrices || []).map(Number).filter((value) => Number.isFinite(value) && value > 0);
  if (!latest || !stop || targets.length < 2) return null;
  const risk = side === "long" ? latest - stop : stop - latest;
  const reward = side === "long" ? targets[1] - latest : latest - targets[1];
  if (risk <= 0 || reward <= 0) return null;
  const riskPct = risk / latest * 100;
  if (riskPct < 0.10 || riskPct > 1.35) return null;
  const expectedRR = reward / risk;
  const confirm = side === "long" ? scores.longScore : scores.shortScore;
  const opposite = side === "long" ? scores.shortScore : scores.longScore;
  const warning = side === "long" ? scores.longWarningScore : scores.shortWarningScore;
  return {
    side,
    setupType,
    entryReason: reason,
    entryPriceZone: `${Math.round(latest - risk * 0.15)}-${Math.round(latest + risk * 0.15)}`,
    invalidPrice: stop,
    targetPrices: targets.slice(0, 3),
    expectedRR,
    riskPct,
    confirm,
    warning,
    scoreEdge: confirm - opposite,
    marketRegime: regime.code,
    marketRegimeLabel: regime.label,
  };
}

function detectBestSetup(metrics, scores, regime) {
  const latest = Number(metrics.latest || 0);
  const atrStep = Math.max(Number(metrics.atr15m || 0), latest * 0.0035);
  const support = Number(metrics.support || 0);
  const resistance = Number(metrics.resistance || 0);
  const vwapValue = Number(metrics.vwap24h || 0);
  const rangePos = simRangePosition(metrics);
  const mid = support && resistance ? (support + resistance) / 2 : latest;
  const psychUp = simPsychLevel(latest, "long");
  const psychDown = simPsychLevel(latest, "short");
  const candidates = [];
  const add = (...args) => {
    const candidate = simSetupCandidate(metrics, regime, ...args, scores);
    if (candidate) candidates.push(candidate);
  };
  if (regime.code === "trend_up" || regime.code === "momentum_up") {
    const pullbackHeld = vwapValue > 0 && latest >= vwapValue && Math.abs(latest - vwapValue) <= atrStep * 0.9 && Number(metrics.macd15m.hist || 0) >= 0;
    const breakout = resistance > 0 && latest > resistance && latest - resistance <= atrStep * 0.55 && Number(metrics.volumeRatio15m || 0) >= 1.12;
    const earlyImpulse = resistance > 0
      && latest >= resistance - atrStep * 0.85
      && latest <= resistance + atrStep * 0.75
      && Number(metrics.change1mPct || 0) > 0.06
      && Number(metrics.volumeRatio1m || 0) >= 1.15
      && (metrics.higherLows1m || metrics.higherLows5m);
    if (pullbackHeld) {
      add("long", "趋势回踩多", Math.min(vwapValue, support || vwapValue) - atrStep * 0.35, [latest + atrStep * 1.4, Math.max(resistance, latest + atrStep * 2.2), Math.max(psychUp + 300, latest + atrStep * 3.1)], "上升趋势里回踩VWAP后重新走强，属于顺势低吸。");
    }
    if (breakout) {
      add("long", "放量突破多", resistance - atrStep * 0.45, [latest + atrStep * 1.2, Math.max(psychUp + 300, latest + atrStep * 2.0), Math.max(psychUp + 700, latest + atrStep * 2.8)], "价格放量突破阻力，回到阻力下方才说明突破失败。");
    }
    if (earlyImpulse) {
      add("long", "冲刺动量多", Math.min(vwapValue || latest, support || latest, latest - atrStep * 0.55), [Math.max(resistance, latest + atrStep * 0.9), Math.max(psychUp + 160, latest + atrStep * 1.7), Math.max(psychUp + 520, latest + atrStep * 2.6)], "短线放量接近突破位，冲刺模式允许提前试多。");
    }
  } else if (regime.code === "trend_down" || regime.code === "momentum_down") {
    const reboundFailed = vwapValue > 0 && latest <= vwapValue && Math.abs(latest - vwapValue) <= atrStep * 0.9 && Number(metrics.macd15m.hist || 0) <= 0;
    const breakdown = support > 0 && latest < support && support - latest <= atrStep * 0.55 && Number(metrics.volumeRatio15m || 0) >= 1.12;
    const earlyImpulse = support > 0
      && latest <= support + atrStep * 0.85
      && latest >= support - atrStep * 0.75
      && Number(metrics.change1mPct || 0) < -0.06
      && Number(metrics.volumeRatio1m || 0) >= 1.15
      && (metrics.lowerHighs1m || metrics.lowerHighs5m);
    if (reboundFailed) {
      add("short", "趋势回踩空", Math.max(vwapValue, resistance || vwapValue) + atrStep * 0.35, [latest - atrStep * 1.4, Math.min(support, latest - atrStep * 2.2), Math.min(psychDown - 300, latest - atrStep * 3.1)], "下降趋势里反弹到VWAP附近受阻，属于顺势高空。");
    }
    if (breakdown) {
      add("short", "放量突破空", support + atrStep * 0.45, [latest - atrStep * 1.2, Math.min(psychDown - 300, latest - atrStep * 2.0), Math.min(psychDown - 700, latest - atrStep * 2.8)], "价格放量跌破支撑，回到支撑上方才说明跌破失败。");
    }
    if (earlyImpulse) {
      add("short", "冲刺动量空", Math.max(vwapValue || latest, resistance || latest, latest + atrStep * 0.55), [Math.min(support, latest - atrStep * 0.9), Math.min(psychDown - 160, latest - atrStep * 1.7), Math.min(psychDown - 520, latest - atrStep * 2.6)], "短线放量接近跌破位，冲刺模式允许提前试空。");
    }
  } else if (regime.code === "range") {
    if (rangePos <= 0.24 && Number(metrics.rsi15m || 50) <= 48 && (metrics.higherLows5m || Number(metrics.macd15m.hist || 0) > 0)) {
      add("long", "区间反转多", support - atrStep * 0.35, [mid, resistance - atrStep * 0.25, resistance + atrStep * 0.55], "价格靠近区间支撑，短线动能开始修复，只做轻仓反弹。");
    }
    if (rangePos >= 0.76 && Number(metrics.rsi15m || 50) >= 52 && (metrics.lowerHighs5m || Number(metrics.macd15m.hist || 0) < 0)) {
      add("short", "区间反转空", resistance + atrStep * 0.35, [mid, support + atrStep * 0.25, support - atrStep * 0.55], "价格靠近区间阻力，短线动能转弱，只做轻仓回落。");
    }
  }
  const filtered = candidates.filter((candidate) => {
    if (candidate.expectedRR < SIM_MIN_EXPECTED_RR) return false;
    if (candidate.side === "long") return scores.longScore >= scores.shortScore - 14 && scores.longWarningScore >= 34;
    return scores.shortScore >= scores.longScore - 14 && scores.shortWarningScore >= 34;
  });
  filtered.sort((a, b) => (b.expectedRR + b.scoreEdge / 100) - (a.expectedRR + a.scoreEdge / 100));
  if (filtered[0]) return filtered[0];
  const reason = regime.code === "chop"
    ? "混沌行情，不交易。"
    : regime.code === "range" && rangePos > 0.24 && rangePos < 0.76
      ? "震荡中间位，无优势，不开仓。"
      : "暂时没有满足盈亏比和结构止损的交易模型。";
  return { side: "flat", setupType: "无合格模型", expectedRR: 0, invalidPrice: 0, targetPrices: [], marketRegime: regime.code, marketRegimeLabel: regime.label, entryReason: reason };
}

function simRiskCheck(state, scores, setup) {
  if (state.balanceCny <= SIM_BLOWUP_RESTART_CNY) return "模拟本金接近归零，等待自动重开下一轮冲刺。";
  if (!setup || setup.side === "flat") return setup?.entryReason || "没有合格交易模型。";
  if (scores.riskScore >= 92) return "极端风险评分过高，禁止开新仓。";
  if (Number(setup.expectedRR || 0) < SIM_MIN_EXPECTED_RR) return `预期盈亏比${Number(setup.expectedRR || 0).toFixed(2)}低于${SIM_MIN_EXPECTED_RR}，不开仓。`;
  return "";
}

function restartSimIfBlownUp(state) {
  if (state.position || Number(state.balanceCny || 0) > SIM_BLOWUP_RESTART_CNY) return false;
  const previousBalance = Number(state.balanceCny || 0);
  state.resetCount = Number(state.resetCount || 0) + 1;
  state.balanceCny = SIM_INITIAL_CNY;
  state.initialCny = SIM_INITIAL_CNY;
  state.maxEquityCny = SIM_INITIAL_CNY;
  state.lossStreak = 0;
  state.lastDecisionAt = null;
  state.lastOpenSide = null;
  pushSimRecord(state, {
    action: "亏完重开模拟",
    side: "flat",
    price: 0,
    quantityBtc: 0,
    marginCny: 0,
    feeCny: 0,
    pnlCny: previousBalance - SIM_INITIAL_CNY,
    balanceCny: state.balanceCny,
    marketRegime: "冲刺实验",
    setupType: "自动重开",
    expectedRR: 0,
    invalidPrice: 0,
    reason: `上一轮余额降至¥${previousBalance.toFixed(2)}，按用户设定允许亏完重开，开启第${state.resetCount + 1}轮5万到10万冲刺。`,
  });
  return true;
}

function simSignalProfile(scores, side, state, setup = null) {
  const confirm = side === "long" ? scores.longScore : scores.shortScore;
  const opposite = side === "long" ? scores.shortScore : scores.longScore;
  const warning = side === "long" ? scores.longWarningScore : scores.shortWarningScore;
  const edge = confirm - opposite;
  const rr = Number(setup?.expectedRR || 0);
  let leverage = SIM_BASE_LEVERAGE;
  let marginPct = SIM_BASE_MARGIN_PCT;
  let lossPct = SIM_BASE_LOSS_PCT;
  let label = "冲刺普通信号";
  if (rr >= 1.75 && confirm >= 58 && warning >= 42 && edge >= 4 && scores.riskScore <= 72) {
    leverage = SIM_STRONG_LEVERAGE;
    marginPct = 0.26;
    lossPct = 0.06;
    label = "冲刺强信号";
  }
  if (rr >= 2.35 && confirm >= 66 && warning >= 50 && edge >= 8 && scores.riskScore <= 62) {
    leverage = SIM_MAX_LEVERAGE;
    marginPct = SIM_MAX_MARGIN_PCT;
    lossPct = SIM_MAX_LOSS_PCT;
    label = "冲刺极强信号";
  }
  if (scores.riskScore >= 75) {
    leverage = Math.min(leverage, SIM_BASE_LEVERAGE);
    marginPct = Math.min(marginPct, 0.18);
    lossPct = Math.min(lossPct, 0.04);
    label += "，极端波动降一档";
  }
  return { leverage, marginPct, lossPct, label, confirm, warning, edge, expectedRR: rr, setupType: setup?.setupType || "" };
}

function simPsychLevel(price, side) {
  if (!Number.isFinite(price) || price <= 0) return 0;
  const step = price >= 10000 ? 1000 : 100;
  return side === "long" ? Math.ceil(price / step) * step : Math.floor(price / step) * step;
}

function simExitProfile(setup = {}, metrics = {}, scores = {}, nearPsych = false) {
  const regime = String(setup.marketRegime || "");
  const setupType = String(setup.setupType || "");
  const expectedRR = Number(setup.expectedRR || 0);
  const scoreEdge = setup.side === "long"
    ? Number(scores.longScore || 0) - Number(scores.shortScore || 0)
    : Number(scores.shortScore || 0) - Number(scores.longScore || 0);
  const volumeHot = Number(metrics.volumeRatio15m || 0) >= 1.25 || Number(metrics.volumeRatio5m || 0) >= 1.35;
  const trendCode = /trend|momentum/.test(regime);
  const rangeCode = regime === "range" || /区间反转/.test(setupType);
  const breakout = /突破|动量/.test(setupType) || nearPsych;
  if (rangeCode) return { code: "full_tp1", ...SIM_EXIT_PROFILES.full_tp1, reason: "震荡/区间模型胜率更依赖快速落袋，第一止盈触发后全部平仓。" };
  if (!trendCode || expectedRR < 1.55 || Number(scores.riskScore || 0) >= 78) {
    return { code: "tp1_heavy", ...SIM_EXIT_PROFILES.tp1_heavy, reason: "行情优势不够单边，第一止盈先落袋大部分，剩余只给一次延伸机会。" };
  }
  if (breakout && volumeHot && scoreEdge >= 12 && expectedRR >= 1.9) {
    return { code: "breakout_runner", ...SIM_EXIT_PROFILES.breakout_runner, reason: "突破/动量模型且量能确认，保留尾仓追踪整数关口和ATR延伸。" };
  }
  return { code: "partial_runner", ...SIM_EXIT_PROFILES.partial_runner, reason: "趋势模型采用分批止盈，保留尾仓验证是否走出单边。" };
}

function buildSimExitPlan(side, entryPrice, riskDistance, metrics = {}, setup = null) {
  const latest = Number(entryPrice || metrics.latest || 0);
  const risk = Math.max(Number(riskDistance || 0), Number(metrics.atr15m || 0) * 1.2, latest * 0.004);
  const psych = simPsychLevel(latest, side);
  const nearPsych = side === "long"
    ? psych > latest && psych - latest <= risk * 2.2
    : psych > 0 && latest - psych <= risk * 2.2;
  let tp1;
  let tp2;
  let runnerTarget;
  let stopLoss;
  if (side === "long") {
    tp1 = latest + risk * 1.8;
    tp2 = latest + risk * 2.9;
    runnerTarget = latest + risk * 3.8;
    if (nearPsych) {
      tp1 = Math.max(tp1, psych + 120);
      tp2 = Math.max(tp2, psych + 500);
      runnerTarget = Math.max(runnerTarget, psych + 800);
    }
    stopLoss = latest - risk;
  } else {
    tp1 = latest - risk * 1.8;
    tp2 = latest - risk * 2.9;
    runnerTarget = latest - risk * 3.8;
    if (nearPsych) {
      tp1 = Math.min(tp1, psych - 120);
      tp2 = Math.min(tp2, psych - 500);
      runnerTarget = Math.min(runnerTarget, psych - 800);
    }
    stopLoss = latest + risk;
  }
  if (setup?.targetPrices?.length >= 2 && Number(setup.invalidPrice || 0) > 0) {
    stopLoss = Number(setup.invalidPrice);
    tp1 = Number(setup.targetPrices[0]);
    tp2 = Number(setup.targetPrices[1]);
    runnerTarget = Number(setup.targetPrices[2] || setup.targetPrices[1]);
  }
  const profile = simExitProfile(setup || {}, metrics, setup?.scores || {}, nearPsych);
  const partialTargets = [
    { id: "tp1", label: "第一止盈", price: tp1, closePct: profile.tp1Pct, hit: false },
  ];
  if (profile.tp2Pct > 0) {
    partialTargets.push({ id: "tp2", label: "第二止盈", price: tp2, closePct: profile.tp2Pct, hit: false });
  }
  return {
    takeProfit: tp1,
    stopLoss,
    runnerTarget: profile.useRunner ? runnerTarget : 0,
    breakoutLevel: nearPsych ? psych : null,
    breakoutMode: nearPsych || profile.code === "breakout_runner",
    exitProfile: profile,
    partialTargets,
  };
}

function ensureSimExitPlan(position, market) {
  if (!position) return null;
  const metrics = market?.metrics || {};
  const entry = Number(position.entryPrice || metrics.latest || 0);
  const stop = Number(position.stopLoss || 0);
  const existingRisk = stop > 0 ? Math.abs(entry - stop) : 0;
  const riskDistance = Math.max(existingRisk, Number(metrics.atr15m || 0) * 1.2, entry * 0.004);
  if (!Array.isArray(position.partialTargets) || !position.exitProfile) {
    const plan = buildSimExitPlan(position.side, entry, riskDistance, metrics);
    const existingTp = Number(position.takeProfit || 0);
    if (existingTp > 0) {
      plan.partialTargets[0].price = existingTp;
      plan.takeProfit = existingTp;
      if (position.side === "long") {
        const psych = simPsychLevel(entry, "long");
        if (psych > entry && existingTp >= psych && plan.partialTargets[1]) {
          plan.partialTargets[1].price = Math.max(plan.partialTargets[1].price, psych + 500);
          plan.runnerTarget = Math.max(plan.runnerTarget, psych + 800);
          plan.breakoutLevel = psych;
          plan.breakoutMode = true;
        }
      } else {
        const psych = simPsychLevel(entry, "short");
        if (psych > 0 && existingTp <= psych && plan.partialTargets[1]) {
          plan.partialTargets[1].price = Math.min(plan.partialTargets[1].price, psych - 500);
          plan.runnerTarget = Math.min(plan.runnerTarget, psych - 800);
          plan.breakoutLevel = psych;
          plan.breakoutMode = true;
        }
      }
    }
    position.partialTargets = plan.partialTargets;
    position.takeProfit = plan.takeProfit;
    position.runnerTarget = plan.runnerTarget;
    position.breakoutLevel = plan.breakoutLevel;
    position.breakoutMode = plan.breakoutMode;
    position.exitProfile = plan.exitProfile;
    position.initialQuantityBtc = Number(position.initialQuantityBtc || position.quantityBtc || 0);
    position.planUpgradedAt = position.planUpgradedAt || new Date().toISOString();
  }
  position.initialQuantityBtc = Number(position.initialQuantityBtc || position.quantityBtc || 0);
  return position;
}

function closeSimPosition(state, market, action, reason, executionPrice = null) {
  const position = state.position;
  if (!position) return 0;
  const latest = Number(executionPrice || market.metrics.latest);
  const rate = market.rateInfo.rate;
  const pnlCny = simPnlCny(position, latest, rate);
  const closeFeeCny = position.quantityBtc * latest * SIM_FEE_RATE * rate;
  const netPnlCny = pnlCny - closeFeeCny;
  state.balanceCny += netPnlCny;
  state.totalTrades += 1;
  if (netPnlCny > 0) {
    state.winTrades += 1;
    state.lossStreak = 0;
  } else {
    state.lossStreak += 1;
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
    marketRegime: position.marketRegime || "",
    setupType: position.setupType || "",
    expectedRR: position.expectedRR || 0,
    invalidPrice: position.invalidPrice || position.stopLoss || 0,
    exitProfile: position.exitProfile?.label || position.exitProfileLabel || "",
    reason,
  });
  state.lastDecisionAt = new Date().toISOString();
  state.lastOpenSide = position.side;
  state.position = null;
  return netPnlCny;
}

function closeSimPartial(state, market, target, reason, executionPrice = null) {
  const position = state.position;
  if (!position) return 0;
  const latest = Number(executionPrice || market.metrics.latest);
  const rate = market.rateInfo.rate;
  const initialQty = Number(position.initialQuantityBtc || position.quantityBtc || 0);
  const closeQty = Math.min(Number(position.quantityBtc || 0), Math.max(0, initialQty * Number(target.closePct || 0)));
  if (!Number.isFinite(closeQty) || closeQty <= 0) return 0;
  if (closeQty >= Number(position.quantityBtc || 0) * 0.999) {
    return closeSimPosition(state, market, target.id === "tp1" ? "第一止盈全平" : "第二止盈全平", reason, latest);
  }
  const rawUsdt = position.side === "long"
    ? (latest - position.entryPrice) * closeQty
    : (position.entryPrice - latest) * closeQty;
  const closeFeeCny = closeQty * latest * SIM_FEE_RATE * rate;
  const netPnlCny = rawUsdt * rate - closeFeeCny;
  state.balanceCny += netPnlCny;
  position.quantityBtc = Math.max(0, Number(position.quantityBtc || 0) - closeQty);
  position.notionalUsdt = position.quantityBtc * position.entryPrice;
  position.marginUsdt = position.leverage ? position.notionalUsdt / position.leverage : position.marginUsdt;
  position.marginCny = position.marginUsdt * rate;
  target.hit = true;
  target.hitAt = new Date().toISOString();
  target.hitPrice = latest;
  if (target.id === "tp1") {
    const risk = Math.abs(Number(position.entryPrice || 0) - Number(position.stopLoss || 0));
    const breakevenBuffer = Math.max(risk * 0.15, Number(position.entryPrice || 0) * 0.001);
    position.stopLoss = position.side === "long"
      ? Math.max(Number(position.stopLoss || 0), Number(position.entryPrice || 0) + breakevenBuffer)
      : Math.min(Number(position.stopLoss || Infinity), Number(position.entryPrice || 0) - breakevenBuffer);
    position.stopMovedAfterTp1 = true;
  }
  pushSimRecord(state, {
    action: target.id === "tp1" ? "第一止盈减仓" : "第二止盈减仓",
    side: position.side,
    price: latest,
    quantityBtc: closeQty,
    marginCny: position.marginCny,
    feeCny: closeFeeCny,
    pnlCny: netPnlCny,
    balanceCny: state.balanceCny,
    marketRegime: position.marketRegime || "",
    setupType: position.setupType || "",
    expectedRR: position.expectedRR || 0,
    invalidPrice: position.invalidPrice || position.stopLoss || 0,
    exitProfile: position.exitProfile?.label || position.exitProfileLabel || "",
    reason,
  });
  if (position.quantityBtc <= Math.max(0.0001, initialQty * 0.05)) {
    closeSimPosition(state, market, "尾仓平仓", "剩余仓位过小，合并平仓。");
  }
  return netPnlCny;
}

function simTrendStillSupportsRunner(position, scores, metrics) {
  if (!position) return false;
  if (scores.riskScore >= 78) return false;
  if (position.side === "long") {
    return scores.longScore >= 70
      && scores.longScore - scores.shortScore >= 14
      && scores.longWarningScore >= 45
      && Number(metrics.latest || 0) > Number(metrics.vwap24h || 0);
  }
  return scores.shortScore >= 70
    && scores.shortScore - scores.longScore >= 14
    && scores.shortWarningScore >= 45
    && Number(metrics.latest || 0) < Number(metrics.vwap24h || Infinity);
}

function extendSimRunnerTarget(state, market, scores, reason) {
  const position = state.position;
  if (!position) return false;
  const metrics = market.metrics;
  const latest = Number(metrics.latest || 0);
  const atrStep = Math.max(Number(metrics.atr15m || 0) * 1.2, latest * 0.004);
  const oldTarget = Number(position.runnerTarget || 0);
  let newTarget;
  if (position.side === "long") {
    const nextPsych = simPsychLevel(Math.max(latest + 1, oldTarget + 1), "long");
    newTarget = Math.max(oldTarget + atrStep * 0.9, latest + atrStep * 1.2, nextPsych + 300);
    position.stopLoss = Math.max(Number(position.stopLoss || 0), latest - atrStep * 0.9, Number(position.entryPrice || 0));
  } else {
    const nextPsych = simPsychLevel(Math.min(latest - 1, oldTarget - 1), "short");
    newTarget = Math.min(oldTarget - atrStep * 0.9, latest - atrStep * 1.2, nextPsych - 300);
    position.stopLoss = Math.min(Number(position.stopLoss || Infinity), latest + atrStep * 0.9, Number(position.entryPrice || 0));
  }
  if (!Number.isFinite(newTarget) || Math.abs(newTarget - oldTarget) < atrStep * 0.25) return false;
  position.runnerTarget = newTarget;
  position.takeProfit = position.takeProfit || newTarget;
  position.runnerExtendedCount = Number(position.runnerExtendedCount || 0) + 1;
  position.lastRunnerExtendedAt = new Date().toISOString();
  pushSimRecord(state, {
    action: "尾仓目标上移",
    side: position.side,
    price: latest,
    quantityBtc: position.quantityBtc,
    marginCny: position.marginCny,
    feeCny: 0,
    pnlCny: 0,
    balanceCny: state.balanceCny,
    marketRegime: position.marketRegime || "",
    setupType: position.setupType || "",
    expectedRR: position.expectedRR || 0,
    invalidPrice: position.invalidPrice || position.stopLoss || 0,
    exitProfile: position.exitProfile?.label || position.exitProfileLabel || "",
    reason,
  });
  return true;
}

function openSimPosition(state, market, setup, scores) {
  const latest = market.metrics.latest;
  const rate = market.rateInfo.rate;
  const equityCny = state.balanceCny;
  const side = setup.side;
  const reason = setup.entryReason;
  const profile = simSignalProfile(scores, side, state, setup);
  const riskDistance = Math.max(Math.abs(latest - Number(setup.invalidPrice || 0)), market.metrics.atr15m * 0.5, latest * 0.001);
  const maxMarginCny = equityCny * profile.marginPct;
  const maxRiskUsdt = equityCny * profile.lossPct / rate;
  const qtyByRisk = maxRiskUsdt / riskDistance;
  const qtyByMargin = (maxMarginCny / rate * profile.leverage) / latest;
  const quantityBtc = Math.max(0, Math.min(qtyByRisk, qtyByMargin));
  const notionalUsdt = quantityBtc * latest;
  const marginUsdt = notionalUsdt / profile.leverage;
  const marginCny = marginUsdt * rate;
  const feeCny = notionalUsdt * SIM_FEE_RATE * rate;
  const exitPlan = buildSimExitPlan(side, latest, riskDistance, market.metrics, { ...setup, scores });
  state.balanceCny -= feeCny;
  state.position = {
    side,
    entryPrice: latest,
    quantityBtc,
    initialQuantityBtc: quantityBtc,
    marginCny,
    marginUsdt,
    notionalUsdt,
    leverage: profile.leverage,
    signalProfile: profile,
    takeProfit: exitPlan.takeProfit,
    stopLoss: exitPlan.stopLoss,
    partialTargets: exitPlan.partialTargets,
    runnerTarget: exitPlan.runnerTarget,
    breakoutLevel: exitPlan.breakoutLevel,
    breakoutMode: exitPlan.breakoutMode,
    exitProfile: exitPlan.exitProfile,
    exitProfileCode: exitPlan.exitProfile?.code || "",
    exitProfileLabel: exitPlan.exitProfile?.label || "",
    marketRegime: setup.marketRegimeLabel || setup.marketRegime || "",
    setupType: setup.setupType,
    expectedRR: setup.expectedRR,
    entryPriceZone: setup.entryPriceZone,
    invalidPrice: setup.invalidPrice,
    targetPrices: setup.targetPrices,
    openedAt: new Date().toISOString(),
    reason: `${reason} 模型：${setup.setupType}，预期盈亏比${Number(setup.expectedRR || 0).toFixed(2)}。杠杆${profile.leverage}x，${profile.label}，单笔风险上限约${(profile.lossPct * 100).toFixed(1)}%。止盈模式：${exitPlan.exitProfile?.label || "自适应止盈"}；${exitPlan.exitProfile?.reason || ""}`,
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
    marketRegime: setup.marketRegimeLabel || setup.marketRegime || "",
    setupType: setup.setupType,
    expectedRR: setup.expectedRR,
    invalidPrice: setup.invalidPrice,
    exitProfile: exitPlan.exitProfile?.label || "",
    reason: state.position.reason,
  });
}

function simEntryQuality(metrics, side) {
  const latest = Number(metrics.latest || 0);
  const atrStep = Math.max(Number(metrics.atr15m || 0), latest * 0.003);
  const support = Number(metrics.support || 0);
  const resistance = Number(metrics.resistance || 0);
  const vwapValue = Number(metrics.vwap24h || 0);
  const vwapDistance = vwapValue ? Math.abs(latest - vwapValue) : Infinity;
  if (side === "long") {
    const pullbackHold = support > 0 && latest >= support && latest - support <= atrStep * 0.85;
    const vwapReclaim = vwapValue > 0 && latest > vwapValue && vwapDistance <= atrStep * 0.75;
    const controlledBreakout = resistance > 0 && latest > resistance && latest - resistance <= atrStep * 0.45 && Number(metrics.volumeRatio15m || 0) >= 1.12;
    if (metrics.priceVsVwapPct > SIM_MAX_VWAP_CHASE_PCT && !controlledBreakout) return "价格已经明显高于VWAP，不追涨，等待回踩或突破确认。";
    if (!pullbackHold && !vwapReclaim && !controlledBreakout) return "入场位置不够好：没有回踩支撑、贴近VWAP或低位突破确认。";
  } else {
    const reboundFail = resistance > 0 && latest <= resistance && resistance - latest <= atrStep * 0.85;
    const vwapReject = vwapValue > 0 && latest < vwapValue && vwapDistance <= atrStep * 0.75;
    const controlledBreakdown = support > 0 && latest < support && support - latest <= atrStep * 0.45 && Number(metrics.volumeRatio15m || 0) >= 1.12;
    if (metrics.priceVsVwapPct < -SIM_MAX_VWAP_CHASE_PCT && !controlledBreakdown) return "价格已经明显低于VWAP，不追空，等待反弹受阻或跌破确认。";
    if (!reboundFail && !vwapReject && !controlledBreakdown) return "入场位置不够好：没有反弹受阻、贴近VWAP或低位跌破确认。";
  }
  return "";
}

function canOpenSim(state, scores, side, metrics) {
  if (state.balanceCny < SIM_INITIAL_CNY * 0.7) return "模拟权益低于初始资金70%，进入保护模式，只允许平仓。";
  if (scores.riskScore >= 80) return "风险评分过高，禁止开新仓。";
  return simEntryQuality(metrics, side);
}

function simCandlesSince(position, metrics) {
  const candles = Array.isArray(metrics.recent1mCandles) ? metrics.recent1mCandles : [];
  const openedAt = new Date(position?.openedAt || 0).getTime();
  const lastCheckedAt = new Date(position?.lastExitCheckAt || position?.openedAt || 0).getTime();
  const from = Math.max(openedAt || 0, lastCheckedAt || 0) - 70 * 1000;
  return candles.filter((item) => Number(item.ts || 0) >= from);
}

function simTouchedPrice(position, metrics, price) {
  const target = Number(price || 0);
  if (!position || !target) return false;
  const candles = simCandlesSince(position, metrics);
  if (position.side === "long") {
    return candles.some((item) => Number(item.high || 0) >= target);
  }
  return candles.some((item) => Number(item.low || 0) <= target);
}

function simTouchedStop(position, metrics) {
  const stop = Number(position?.stopLoss || 0);
  if (!position || !stop) return false;
  const candles = simCandlesSince(position, metrics);
  if (position.side === "long") {
    return Number(metrics.latest || 0) <= stop || candles.some((item) => Number(item.low || 0) <= stop);
  }
  return Number(metrics.latest || 0) >= stop || candles.some((item) => Number(item.high || 0) >= stop);
}

function runSimDecision(state, market) {
  restartSimIfBlownUp(state);
  const metrics = market.metrics;
  const scores = simScores(metrics);
  const marketRegime = classifyMarketRegime(metrics, scores);
  const selectedSetup = detectBestSetup(metrics, scores, marketRegime);
  const rate = market.rateInfo.rate;
  let decision = "观望";
  let reason = selectedSetup.entryReason || marketRegime.reason;
  if (state.position) {
    const position = state.position;
    ensureSimExitPlan(position, market);
    if (simTouchedStop(position, metrics)) {
      const protectiveProfit = Boolean(position.stopMovedAfterTp1);
      const stopAction = protectiveProfit ? "移动止盈平仓" : "止损平仓";
      const stopReason = protectiveProfit ? "1分钟K线触及第一止盈后的移动保护位，保住剩余仓位利润。" : "1分钟K线触及开仓时锁定止损，优先控制单笔亏损。";
      closeSimPosition(state, market, stopAction, stopReason, Number(position.stopLoss || metrics.latest));
      decision = stopAction;
      reason = protectiveProfit ? "1分钟K线触及移动保护位。" : "1分钟K线触及开仓时锁定止损。";
    } else {
      const nextTarget = (position.partialTargets || []).find((target) => !target.hit);
      const hitPartial = nextTarget && simTouchedPrice(position, metrics, Number(nextTarget.price || 0));
      const hitRunner = !hitPartial && Number(position.runnerTarget || 0) > 0 && (
        simTouchedPrice(position, metrics, Number(position.runnerTarget || 0))
      );
      if (hitPartial) {
        const fullTarget = Number(nextTarget.closePct || 0) >= 0.999;
        const label = fullTarget ? (nextTarget.id === "tp1" ? "第一止盈全平" : "第二止盈全平") : (nextTarget.id === "tp1" ? "第一止盈减仓" : "第二止盈减仓");
        const exitProfileText = position.exitProfile?.label || "自适应止盈";
        const partialReason = fullTarget
          ? `${nextTarget.label || label}触发，当前止盈模式为“${exitProfileText}”，按计划全部平仓。`
          : `${nextTarget.label || label}触发，当前止盈模式为“${exitProfileText}”，先落袋一部分，剩余仓位继续看突破延伸。`;
        closeSimPartial(state, market, nextTarget, partialReason, Number(nextTarget.price || metrics.latest));
        decision = label;
        reason = partialReason;
      } else if (hitRunner) {
        if (simTrendStillSupportsRunner(position, scores, metrics)) {
          const oldTarget = Number(position.runnerTarget || 0);
          extendSimRunnerTarget(state, market, scores, `尾仓目标${oldTarget.toFixed(1)}已到，但趋势评分仍强，不平仓追单，改为上移目标并抬高保护止损。`);
          decision = "尾仓目标上移";
          reason = "尾仓目标已到，但趋势仍强，继续持有尾仓并上移目标。";
        } else {
          closeSimPosition(state, market, "尾仓止盈", "1分钟K线触及尾仓突破目标，且趋势延伸条件不足，退出剩余仓位。", Number(position.runnerTarget || metrics.latest));
          decision = "尾仓止盈";
          reason = "1分钟K线触及尾仓突破目标，趋势延伸条件不足。";
        }
      } else if (!Array.isArray(position.partialTargets) && simTouchedPrice(position, metrics, Number(position.takeProfit || 0))) {
        closeSimPosition(state, market, "止盈平仓", "1分钟K线触及开仓时锁定止盈，落袋为安。", Number(position.takeProfit || metrics.latest));
        decision = "止盈平仓";
        reason = "1分钟K线触及开仓时锁定止盈。";
      } else if (position.side === "long" && metrics.latest < Math.min(Number(position.invalidPrice || position.stopLoss || 0), Number(metrics.vwap24h || Infinity)) && scores.shortScore - scores.longScore >= 24 && scores.shortWarningScore >= 62) {
        closeSimPosition(state, market, "反向结构平仓", "多单结构跌破，同时空头评分占优，退出多单。");
        decision = "反向信号平仓";
        reason = "多单结构跌破，同时空头评分占优。";
      } else if (position.side === "short" && metrics.latest > Math.max(Number(position.invalidPrice || position.stopLoss || 0), Number(metrics.vwap24h || 0)) && scores.longScore - scores.shortScore >= 24 && scores.longWarningScore >= 62) {
        closeSimPosition(state, market, "反向结构平仓", "空单结构突破，同时多头评分占优，退出空单。");
        decision = "反向信号平仓";
        reason = "空单结构突破，同时多头评分占优。";
      } else {
        decision = "持仓";
        if (position.breakoutMode && position.breakoutLevel) {
          reason = `已有仓位按${position.exitProfile?.label || "突破管理"}执行：先看${position.breakoutLevel}整数关口是否站稳，再决定尾仓是否延伸。`;
        } else {
          reason = `已有仓位未触及止盈止损，${position.exitProfile?.label || "自适应止盈"}计划继续执行。`;
        }
      }
      if (state.position) state.position.lastExitCheckAt = new Date().toISOString();
    }
  }
  if (!state.position && !["止损平仓", "止盈平仓", "第一止盈减仓", "第二止盈减仓", "第一止盈全平", "第二止盈全平", "移动止盈平仓", "尾仓止盈", "尾仓平仓", "反向信号平仓"].includes(decision)) {
    const blockReason = simRiskCheck(state, scores, selectedSetup);
    if (blockReason) {
      decision = selectedSetup?.side === "flat" || /模型|盈亏比|中间位|混沌/.test(blockReason) ? "入场过滤未通过" : "风控禁止开仓";
      reason = blockReason;
    } else {
      openSimPosition(state, market, selectedSetup, scores);
      decision = selectedSetup.side === "long" ? "开多" : "开空";
      reason = selectedSetup.entryReason;
    }
  }
  if (["观望", "风控禁止开仓", "入场过滤未通过"].includes(decision)) {
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
        marketRegime: marketRegime.label,
        setupType: selectedSetup?.setupType || "",
        expectedRR: selectedSetup?.expectedRR || 0,
        invalidPrice: selectedSetup?.invalidPrice || 0,
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
    marketRegime,
    selectedSetup,
    floatingPnlCny,
    equityCny,
    drawdownPct: state.maxEquityCny ? (equityCny / state.maxEquityCny - 1) * 100 : 0,
    winRate: state.totalTrades ? state.winTrades / state.totalTrades * 100 : 0,
  };
}

async function runSimCycle(env, trigger = "api") {
  if (!env.ACCOUNT_KV) throw new Error("ACCOUNT_KV 未绑定，模拟盘无法保存状态");
  const [state, market] = await Promise.all([readSimState(env), simMarketSnapshot()]);
  state.pauseUntil = null;
  state.lastSimTrigger = trigger;
  const result = runSimDecision(state, market);
  if (trigger === "scheduled" || trigger === "github-cron") state.lastScheduledRunAt = new Date().toISOString();
  await writeSimState(env, state);
  return { state, market, result };
}

async function simBrief(request, env) {
  try {
    if (!env.ACCOUNT_KV) return jsonResponse({ ok: false, error: "ACCOUNT_KV 未绑定，模拟盘无法保存状态" }, 500);
    const url = new URL(request.url);
    if (request.method === "POST" && url.pathname === "/sim/reset") {
      const state = emptySimState();
      pushSimRecord(state, { action: "重置模拟盘", side: "flat", price: 0, quantityBtc: 0, marginCny: 0, feeCny: 0, pnlCny: 0, balanceCny: state.balanceCny, reason: "手动重置为初始本金¥50,000。" });
      await writeSimState(env, state);
      return jsonResponse({ ok: true, reset: true, state });
    }
    const requestedTrigger = url.searchParams.get("trigger") === "github-cron" ? "github-cron" : "api";
    const { state, market, result } = await runSimCycle(env, requestedTrigger);
    return jsonResponse({
      ok: true,
      source: "ai-sim-worker",
      marketSource: market.source,
      sourceWarning: market.sourceWarning || "",
      updatedAt: state.updatedAt,
      balanceCny: state.balanceCny,
      equityCny: result.equityCny,
      floatingPnlCny: result.floatingPnlCny,
      initialCny: state.initialCny,
      targetCny: SIM_TARGET_CNY,
      sprintDays: SIM_SPRINT_DAYS,
      resetCount: state.resetCount || 0,
      maxEquityCny: state.maxEquityCny,
      drawdownPct: result.drawdownPct,
      winRate: result.winRate,
      totalTrades: state.totalTrades,
      winTrades: state.winTrades,
      lossStreak: state.lossStreak,
      pauseUntil: state.pauseUntil,
      lastSimTrigger: state.lastSimTrigger || "api",
      lastScheduledRunAt: state.lastScheduledRunAt || null,
      decision: result.decision,
      decisionReason: result.reason,
      scores: result.scores,
      marketRegime: result.marketRegime,
      selectedSetup: result.selectedSetup,
      position: state.position,
      records: (state.records || []).slice(0, 100),
      market: {
        latest: market.metrics.latest,
        source: market.source,
        sourceWarning: market.sourceWarning || "",
        cnyRate: market.rateInfo.rate,
        cnyRateSource: market.rateInfo.source,
        funding: market.metrics.funding,
        support: market.metrics.support,
        resistance: market.metrics.resistance,
        vwap24h: market.metrics.vwap24h,
      },
      riskRules: {
        baseMarginPct: SIM_BASE_MARGIN_PCT,
        maxMarginPct: SIM_MAX_MARGIN_PCT,
        baseLossPct: SIM_BASE_LOSS_PCT,
        maxLossPct: SIM_MAX_LOSS_PCT,
        baseLeverage: SIM_BASE_LEVERAGE,
        strongLeverage: SIM_STRONG_LEVERAGE,
        maxLeverage: SIM_MAX_LEVERAGE,
        feeRate: SIM_FEE_RATE,
        observationLogIntervalMinutes: SIM_COOLDOWN_MS / 60000,
        timeCooldownRemoved: true,
        backgroundCron: "*/5 * * * *",
        minExpectedRR: SIM_MIN_EXPECTED_RR,
        minConfirmScore: SIM_MIN_CONFIRM_SCORE,
        minWarningScore: SIM_MIN_WARNING_SCORE,
        minScoreEdge: SIM_MIN_SCORE_EDGE,
        maxVwapChasePct: SIM_MAX_VWAP_CHASE_PCT,
        blowupRestartCny: SIM_BLOWUP_RESTART_CNY,
        mode: "aggressive_sprint",
        objective: "7天内5万冲刺到10万，允许归零后重开模拟",
        exitProfiles: SIM_EXIT_PROFILES,
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
      title: "美国8月PPI生产者价格指数",
      country: "US",
      category: "Producer Price Index",
      type: "经济数据",
      scheduledAt: "2026-09-10T12:30:00.000Z",
      impact: "中高",
      forecast: "市场预期：PPI同比约5.3%；重点看Final Demand和核心PPI是否继续偏热。",
      previous: "7月PPI同比约4.8%；前值用于判断通胀压力是否重新抬头。",
      actual: "Final Demand PPI环比+0.4%、同比+5.4%；核心PPI同比+4.6%。",
      status: "已公布",
      source: "BLS官方PPI发布",
      btcDirection: "短线偏利空BTC：PPI略高于预期，说明上游通胀压力仍偏强，可能压制降息交易；但最终方向仍要看CPI和FOMC表态是否确认。",
    },
    {
      title: "美联储9月15-16日FOMC议息观察窗口",
      country: "US",
      category: "FOMC",
      type: "美联储",
      scheduledAt: "2026-09-15T00:00:00.000Z",
      impact: "高",
      forecast: "议息观察窗口开始；市场重点关注是否维持利率不变、点阵图和鲍威尔对后续路径的表态。",
      previous: "上次会议维持政策利率不变，市场继续交易后续降息/维持高利率路径。",
      actual: "",
      status: "待公布",
      source: "Federal Reserve FOMC日程",
      btcDirection: "待公布：若维持不变但释放降息信号，偏利多BTC；若维持不变且措辞鹰派，偏利空BTC；若意外加息，短线明显利空BTC。",
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
    const until = new Date(now.getTime() + UPCOMING_MACRO_WINDOW_MS);
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
    const until = new Date(now.getTime() + UPCOMING_MACRO_WINDOW_MS);
    const recentFrom = new Date(now.getTime() - RECENT_MACRO_KEEP_MS);
    return (t >= now && t <= until) || (event.status === "已公布" && t >= recentFrom && t <= now);
  });
}

async function readMacroObservationSnapshot(env) {
  if (!env.ACCOUNT_KV) return {};
  try {
    const raw = await env.ACCOUNT_KV.get(MACRO_OBS_KV_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

async function writeMacroObservationSnapshot(env, events) {
  if (!env.ACCOUNT_KV) return;
  const snapshot = {};
  for (const event of events || []) {
    snapshot[event.id || event.title] = {
      updatedAt: event.updatedAt,
      metrics: (event.metrics || []).map((metric) => ({
        key: metric.key,
        label: metric.label,
        value: metric.value,
        unit: metric.unit,
        display: metric.display,
      })),
    };
  }
  await env.ACCOUNT_KV.put(MACRO_OBS_KV_KEY, JSON.stringify(snapshot));
}

function priorMetric(previousSnapshot, eventId, metricKey) {
  const event = previousSnapshot?.[eventId];
  const metric = (event?.metrics || []).find((item) => item.key === metricKey);
  return metric || null;
}

function formatMacroValue(value, unit = "", decimals = 2) {
  if (value === null || value === undefined || value === "") return "未接入";
  if (typeof value === "string") return value;
  if (!Number.isFinite(Number(value))) return "未接入";
  const number = Number(value);
  if (unit === "亿美元") return `${(number / 100000000).toFixed(decimals)}亿美元`;
  if (unit === "十亿美元") return `${(number / 1000000000).toFixed(decimals)}十亿美元`;
  if (unit === "%") return `${number.toFixed(decimals)}%`;
  if (unit === "bp") return `${number >= 0 ? "+" : ""}${number.toFixed(decimals)}bp`;
  return `${number.toFixed(decimals)}${unit || ""}`;
}

function macroMetric({ key, label, value, unit = "", previousMetric = null, threshold = "", decimals = 2, updatedAt = "" }) {
  const priorValue = previousMetric && Number.isFinite(Number(previousMetric.value)) ? Number(previousMetric.value) : null;
  const numeric = Number.isFinite(Number(value)) ? Number(value) : null;
  const change = numeric !== null && priorValue !== null ? numeric - priorValue : null;
  return {
    key,
    label,
    value: numeric === null ? value : numeric,
    unit,
    display: formatMacroValue(numeric === null ? value : numeric, unit, decimals),
    previous: priorValue === null ? (previousMetric?.display || "前值建立中") : formatMacroValue(priorValue, unit, decimals),
    change: change === null ? "前值建立中" : formatMacroValue(change, unit === "%" ? "百分点" : unit, decimals),
    threshold,
    updatedAt,
  };
}

async function yahooChartMetric(symbol) {
  const encoded = encodeURIComponent(symbol);
  const payload = await fetchJsonOptional(`https://query1.finance.yahoo.com/v8/finance/chart/${encoded}?range=5d&interval=1d`, null, 300);
  const result = payload?.chart?.result?.[0];
  const quote = result?.indicators?.quote?.[0] || {};
  const closes = (quote.close || []).map((item) => Number(item)).filter((item) => Number.isFinite(item));
  const latest = closes[closes.length - 1] ?? null;
  const previous = closes[closes.length - 2] ?? null;
  return { latest, previous };
}

async function stablecoinSupplyMetric() {
  const payload = await fetchJsonOptional("https://stablecoins.llama.fi/stablecoins?includePrices=true", null, 900);
  const assets = Array.isArray(payload?.peggedAssets) ? payload.peggedAssets : [];
  let current = 0;
  let prevDay = 0;
  let prevWeek = 0;
  for (const asset of assets) {
    current += Number(asset?.circulating?.peggedUSD || 0);
    prevDay += Number(asset?.circulatingPrevDay?.peggedUSD || 0);
    prevWeek += Number(asset?.circulatingPrevWeek?.peggedUSD || 0);
  }
  if (!current) return null;
  return {
    current,
    oneDayPct: prevDay ? (current / prevDay - 1) * 100 : null,
    sevenDayPct: prevWeek ? (current / prevWeek - 1) * 100 : null,
  };
}

async function treasuryAuctionMetric(now) {
  const today = now.toISOString().slice(0, 10);
  const url = `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query?filter=auction_date:gte:${today}&sort=auction_date&page[size]=5`;
  const payload = await fetchJsonOptional(url, null, 3600);
  const item = Array.isArray(payload?.data) ? payload.data[0] : null;
  if (!item) return null;
  return {
    auctionDate: item.auction_date || item.record_date || "",
    securityTerm: item.security_term || item.security_type || "美债",
    offeringAmount: numberOrNull(item.offering_amt || item.offering_amount),
    bidToCover: numberOrNull(item.bid_to_cover_ratio),
    highYield: numberOrNull(item.high_yield || item.high_investment_rate),
  };
}

async function btcEtfFlowMetric() {
  const html = await fetchTextOptional("https://farside.co.uk/btc/", "", 1800);
  if (!html) return null;
  const rows = [...html.matchAll(/<tr[\s\S]*?<\/tr>/gi)].map((match) => match[0]);
  const dailyValues = [];
  for (const row of rows) {
    const text = row.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
    if (!/\d{1,2}\s[A-Za-z]{3}|\d{1,2}\/\d{1,2}/.test(text)) continue;
    const numbers = [...text.matchAll(/-?\$?\d[\d,]*(?:\.\d+)?/g)]
      .map((match) => numberOrNull(match[0]))
      .filter((value) => value !== null);
    const total = numbers[numbers.length - 1];
    if (Number.isFinite(total)) dailyValues.push(total * 1000000);
    if (dailyValues.length >= 3) break;
  }
  if (!dailyValues.length) return null;
  return {
    latest: dailyValues[0],
    previous: dailyValues[1] ?? null,
    threeDay: dailyValues.reduce((sum, value) => sum + value, 0),
  };
}

async function marketMacroSignalEvents(now, env, previousSnapshot) {
  const updatedAt = now.toISOString();
  const [dxy, tnx, auction] = await Promise.all([
    yahooChartMetric("DX-Y.NYB"),
    yahooChartMetric("^TNX"),
    treasuryAuctionMetric(now),
  ]);
  const dxyChangePct = dxy.latest && dxy.previous ? (dxy.latest / dxy.previous - 1) * 100 : null;
  const tnxYield = tnx.latest ? (tnx.latest > 20 ? tnx.latest / 10 : tnx.latest) : null;
  const tnxPrevYield = tnx.previous ? (tnx.previous > 20 ? tnx.previous / 10 : tnx.previous) : null;
  const tnxChangeBp = tnxYield !== null && tnxPrevYield !== null ? (tnxYield - tnxPrevYield) * 100 : null;
  const dollarYieldSignal = dxyChangePct !== null && tnxChangeBp !== null
    ? (dxyChangePct >= 0.5 && tnxChangeBp >= 8 ? "偏利空BTC：美元和美债收益率同步走强。" : dxyChangePct <= -0.5 && tnxChangeBp <= -8 ? "偏利多BTC：美元和美债收益率同步走弱。" : "中性：美元与美债未同时触发关键临界值。")
    : "数据源不可用：先按阈值观察，等待下一轮刷新。";
  return [
    {
      id: "fedwatch-rate-probability",
      title: "CME FedWatch利率概率观察",
      country: "US",
      category: "Rate Expectations",
      type: "利率预期",
      scheduledAt: null,
      updateFrequency: "实时变化",
      impact: "高",
      forecast: "观察降息/维持/加息概率是否相对前值快速变化。",
      previous: "前值由CME公开页面抓取能力决定；未抓到时只显示阈值参考。",
      actual: "",
      status: "观察",
      source: "CME FedWatch免费网页观察",
      sourceUrls: ["https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"],
      dataQuality: "threshold_only",
      numericSignal: "阈值参考",
      updatedAt,
      metrics: [
        macroMetric({ key: "cutProbability", label: "降息概率", value: "公开页暂未稳定抓取", unit: "%", previousMetric: priorMetric(previousSnapshot, "fedwatch-rate-probability", "cutProbability"), threshold: "较前值上升10个百分点以上：偏利多BTC", updatedAt }),
        macroMetric({ key: "hawkishProbability", label: "维持/加息概率", value: "公开页暂未稳定抓取", unit: "%", previousMetric: priorMetric(previousSnapshot, "fedwatch-rate-probability", "hawkishProbability"), threshold: "较前值上升10个百分点以上：偏利空BTC", updatedAt }),
      ],
      thresholds: ["降息概率较前值+10个百分点：偏利多", "维持高利率/加息概率较前值+10个百分点：偏利空"],
      btcDirection: "阈值参考：降息概率明显上升偏利多BTC；维持高利率或加息概率上升偏利空BTC。",
    },
    {
      id: "treasury-auction-pressure",
      title: "美国财政部美债拍卖与再融资观察",
      country: "US",
      category: "Treasury Auctions",
      type: "美债流动性",
      scheduledAt: null,
      updateFrequency: "按拍卖日程/季度再融资公告更新",
      impact: "中高",
      forecast: auction ? `${auction.auctionDate} ${auction.securityTerm}；规模${auction.offeringAmount ? formatMacroValue(auction.offeringAmount, "亿美元", 1) : "待官方更新"}` : "下一场拍卖日程暂未抓到，继续使用阈值观察。",
      previous: "前次投标倍数/尾差公布后进入数值面板。",
      actual: auction?.bidToCover ? `投标倍数${auction.bidToCover}` : "",
      status: "观察",
      source: "U.S. Treasury auction schedule",
      sourceUrls: ["https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding", "https://www.treasurydirect.gov/auctions/upcoming/"],
      dataQuality: auction ? "delayed" : "threshold_only",
      numericSignal: auction ? "等待拍卖结果" : "阈值参考",
      updatedAt,
      metrics: [
        macroMetric({ key: "nextAuctionAmount", label: "下一场规模", value: auction?.offeringAmount ?? "待官方更新", unit: "亿美元", previousMetric: priorMetric(previousSnapshot, "treasury-auction-pressure", "nextAuctionAmount"), threshold: "长债大规模供给且收益率上行：风险升高", decimals: 1, updatedAt }),
        macroMetric({ key: "bidToCover", label: "投标倍数", value: auction?.bidToCover ?? "待公布", unit: "", previousMetric: priorMetric(previousSnapshot, "treasury-auction-pressure", "bidToCover"), threshold: "低于近6次均值：偏利空BTC", decimals: 2, updatedAt }),
        macroMetric({ key: "tail", label: "尾差", value: "待公布", unit: "bp", previousMetric: priorMetric(previousSnapshot, "treasury-auction-pressure", "tail"), threshold: "尾差 > +1bp：偏利空BTC", updatedAt }),
      ],
      thresholds: ["尾差 > +1bp：偏利空", "投标倍数低于近6次均值：偏利空", "拍卖需求强且收益率回落：偏利多"],
      btcDirection: "方向规则：拍卖需求强、收益率回落偏利多BTC；拍卖需求弱、收益率上行偏利空BTC。",
    },
    {
      id: "dxy-yield-linkage",
      title: "美元指数与美债收益率联动观察",
      country: "US",
      category: "Dollar and Yields",
      type: "美元/美债",
      scheduledAt: null,
      updateFrequency: "实时观察",
      impact: "中高",
      forecast: "观察DXY与10年美债收益率是否同向触发临界值。",
      previous: dxy.previous && tnxPrevYield ? `DXY ${dxy.previous.toFixed(2)}；10年美债 ${tnxPrevYield.toFixed(2)}%` : "前值建立中",
      actual: dxy.latest && tnxYield ? `DXY ${dxy.latest.toFixed(2)}；10年美债 ${tnxYield.toFixed(2)}%` : "",
      status: "观察",
      source: "Yahoo Finance market proxy / Treasury",
      sourceUrls: ["https://fred.stlouisfed.org/series/DGS10", "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"],
      dataQuality: dxy.latest && tnxYield ? "delayed" : "unavailable",
      numericSignal: dollarYieldSignal,
      updatedAt,
      metrics: [
        macroMetric({ key: "dxy", label: "DXY", value: dxy.latest ?? "行情源不可用", unit: "", previousMetric: priorMetric(previousSnapshot, "dxy-yield-linkage", "dxy"), threshold: "单日 +0.5% 且10Y +8bp：偏利空BTC", decimals: 2, updatedAt }),
        macroMetric({ key: "dxyChange", label: "DXY日变化", value: dxyChangePct ?? "行情源不可用", unit: "%", previousMetric: priorMetric(previousSnapshot, "dxy-yield-linkage", "dxyChange"), threshold: "+0.5% / -0.5%", decimals: 2, updatedAt }),
        macroMetric({ key: "us10y", label: "10年美债", value: tnxYield ?? "行情源不可用", unit: "%", previousMetric: priorMetric(previousSnapshot, "dxy-yield-linkage", "us10y"), threshold: "单日 +8bp 偏利空，-8bp 偏利多", decimals: 2, updatedAt }),
        macroMetric({ key: "us10yChange", label: "10Y变化", value: tnxChangeBp ?? "行情源不可用", unit: "bp", previousMetric: priorMetric(previousSnapshot, "dxy-yield-linkage", "us10yChange"), threshold: "+8bp / -8bp", decimals: 1, updatedAt }),
      ],
      thresholds: ["DXY +0.5% 且10年美债 +8bp：偏利空", "DXY -0.5% 且10年美债 -8bp：偏利多"],
      btcDirection: dollarYieldSignal,
    },
  ];
}

async function cryptoFlowEvents(now, env, previousSnapshot) {
  const updatedAt = now.toISOString();
  const [etf, stablecoins] = await Promise.all([
    btcEtfFlowMetric(),
    stablecoinSupplyMetric(),
  ]);
  const etfSignal = etf?.threeDay >= 500000000
    ? "偏利多BTC：ETF三日净流入超过5亿美元。"
    : etf?.threeDay <= -300000000
      ? "偏利空BTC：ETF三日净流出超过3亿美元。"
      : etf
        ? "中性：ETF三日流量未触发关键临界值。"
        : "数据源不可用：等待公开ETF流量源恢复。";
  const stableSignal = stablecoins?.sevenDayPct >= 0.5
    ? "偏利多BTC：稳定币供应7日扩张超过0.5%。"
    : stablecoins?.sevenDayPct <= -0.5
      ? "偏利空BTC：稳定币供应7日收缩超过0.5%。"
      : stablecoins
        ? "中性：稳定币供应变化未触发关键临界值。"
        : "数据源不可用：等待DefiLlama恢复。";
  return [
    {
      id: "btc-etf-flow",
      title: "美国现货BTC ETF资金流观察",
      country: "US",
      category: "BTC ETF Flow",
      type: "ETF资金流",
      scheduledAt: null,
      updateFrequency: "美股收盘后/资金流源更新后",
      impact: "高",
      forecast: "观察最近一日和三日合计净流入/净流出。",
      previous: etf?.previous !== null && etf?.previous !== undefined ? formatMacroValue(etf.previous, "亿美元", 2) : "前值建立中",
      actual: etf?.latest !== null && etf?.latest !== undefined ? formatMacroValue(etf.latest, "亿美元", 2) : "",
      status: "观察",
      source: "ETF公开流量聚合源",
      sourceUrls: ["https://farside.co.uk/btc/"],
      dataQuality: etf ? "delayed" : "unavailable",
      numericSignal: etfSignal,
      updatedAt,
      metrics: [
        macroMetric({ key: "latestNetFlow", label: "最近一日净流", value: etf?.latest ?? "资金流源不可用", unit: "亿美元", previousMetric: priorMetric(previousSnapshot, "btc-etf-flow", "latestNetFlow"), threshold: "单日大额净流入增强现货买盘", decimals: 2, updatedAt }),
        macroMetric({ key: "threeDayNetFlow", label: "3日合计", value: etf?.threeDay ?? "资金流源不可用", unit: "亿美元", previousMetric: priorMetric(previousSnapshot, "btc-etf-flow", "threeDayNetFlow"), threshold: "> +5亿美元偏利多；< -3亿美元偏利空", decimals: 2, updatedAt }),
      ],
      thresholds: ["3日净流入 > +5亿美元：偏利多", "3日净流出 < -3亿美元：偏利空"],
      btcDirection: etfSignal,
    },
    {
      id: "stablecoin-liquidity",
      title: "稳定币流动性与交易所资金观察",
      country: "Global",
      category: "Stablecoin Liquidity",
      type: "稳定币流动性",
      scheduledAt: null,
      updateFrequency: "每日观察",
      impact: "中高",
      forecast: "观察稳定币总供应和7日变化。",
      previous: "前值由上一轮Worker快照保存；DefiLlama也提供1日/7日供应对比。",
      actual: stablecoins?.current ? formatMacroValue(stablecoins.current, "十亿美元", 2) : "",
      status: "观察",
      source: "DefiLlama stablecoins / exchange flow proxy",
      sourceUrls: ["https://defillama.com/stablecoins"],
      dataQuality: stablecoins ? "delayed" : "unavailable",
      numericSignal: stableSignal,
      updatedAt,
      metrics: [
        macroMetric({ key: "stablecoinSupply", label: "稳定币总供应", value: stablecoins?.current ?? "DefiLlama不可用", unit: "十亿美元", previousMetric: priorMetric(previousSnapshot, "stablecoin-liquidity", "stablecoinSupply"), threshold: "供应扩张支撑风险偏好", decimals: 2, updatedAt }),
        macroMetric({ key: "stablecoin1d", label: "1日变化", value: stablecoins?.oneDayPct ?? "DefiLlama不可用", unit: "%", previousMetric: priorMetric(previousSnapshot, "stablecoin-liquidity", "stablecoin1d"), threshold: "+0.2% / -0.2%", decimals: 2, updatedAt }),
        macroMetric({ key: "stablecoin7d", label: "7日变化", value: stablecoins?.sevenDayPct ?? "DefiLlama不可用", unit: "%", previousMetric: priorMetric(previousSnapshot, "stablecoin-liquidity", "stablecoin7d"), threshold: "> +0.5%偏利多；< -0.5%偏利空", decimals: 2, updatedAt }),
      ],
      thresholds: ["7日供应 +0.5%以上：偏利多", "7日供应 -0.5%以上：偏利空"],
      btcDirection: stableSignal,
    },
  ];
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
  const until = new Date(now.getTime() + UPCOMING_MACRO_WINDOW_MS);
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
  const previousObservationSnapshot = await readMacroObservationSnapshot(env);
  const officialEvents = officialMacroEvents(now);
  const cryptoPolicyEvents = policyCryptoEvents(now);
  const [rateAndLiquidityEvents, cryptoFlowSignalEvents] = await Promise.all([
    marketMacroSignalEvents(now, env, previousObservationSnapshot),
    cryptoFlowEvents(now, env, previousObservationSnapshot),
  ]);
  if (officialEvents.length || cryptoPolicyEvents.length || rateAndLiquidityEvents.length || cryptoFlowSignalEvents.length) sources.push(FREE_MACRO_SOURCE);
  const observationEvents = [...rateAndLiquidityEvents, ...cryptoFlowSignalEvents];
  await writeMacroObservationSnapshot(env, observationEvents);
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
      title: "未来7天暂无已接入的高影响宏观事件",
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
    observationEvents,
    policyCryptoEvents: cryptoPolicyEvents,
    rateAndLiquidityEvents,
    cryptoFlowEvents: cryptoFlowSignalEvents,
    warnings,
    macroStatus: {
      tradingEconomicsConfigured: Boolean(env.TRADING_ECONOMICS_KEY),
      officialFallbackActive: true,
      freeOfficialMode: !env.TRADING_ECONOMICS_KEY,
      recentKeepHours: RECENT_MACRO_KEEP_MS / (60 * 60 * 1000),
      upcomingWindowHours: UPCOMING_MACRO_WINDOW_MS / (60 * 60 * 1000),
      policyCryptoKeywords: POLICY_CRYPTO_KEYWORDS,
      sourceCategories: ["经济数据", "美联储", "利率预期", "美债流动性", "美元/美债", "ETF资金流", "稳定币流动性", "加密政策"],
    },
  });
}

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(runSimCycle(env, "scheduled").catch((error) => {
      console.error("scheduled sim cycle failed", error);
    }));
  },
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
