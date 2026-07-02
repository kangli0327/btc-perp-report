const OKX_BASE = "https://www.okx.com";
const FALLBACK_CNY_RATE = 7.2;

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
      "Cache-Control": "no-store",
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
    return Number.isFinite(rate) && rate > 0 ? { rate, source: "Coinbase USDT/CNY" } : { rate: FALLBACK_CNY_RATE, source: "fallback" };
  } catch {
    return { rate: FALLBACK_CNY_RATE, source: "fallback" };
  }
}

function beijingWeekKey(now = new Date()) {
  const bj = new Date(now.getTime() + 8 * 60 * 60 * 1000);
  const day = bj.getUTCDay() || 7;
  bj.setUTCDate(bj.getUTCDate() - day + 1);
  bj.setUTCHours(0, 0, 0, 0);
  return bj.toISOString().slice(0, 10);
}

function weeklyRiskPct(equityCny) {
  if (equityCny < 10000) return 0.25;
  if (equityCny < 30000) return 0.18;
  if (equityCny < 100000) return 0.12;
  return 0.08;
}

function parsePosition(positions, instruments) {
  const inst = instruments.find((item) => item.instId === "BTC-USDT-SWAP") || {};
  const contractValue = Number(inst.ctVal || 0.01);
  const active = positions.find((item) => Math.abs(Number(item.pos || 0)) > 0);
  if (!active) return null;
  const rawPos = Number(active.pos || 0);
  const posSide = active.posSide === "net" ? (rawPos < 0 ? "short" : "long") : active.posSide;
  return {
    side: posSide === "short" ? "short" : "long",
    quantityBtc: Math.abs(rawPos) * contractValue,
    contracts: Math.abs(rawPos),
    entryPrice: Number(active.avgPx || 0),
    leverage: Number(active.lever || 100),
    marginUsdt: Number(active.margin || active.imr || 0),
    liquidationPrice: Number(active.liqPx || 0),
    uplUsdt: Number(active.upl || 0),
  };
}

async function weeklyLoss(env, equityCny) {
  const key = `week-start:${beijingWeekKey()}`;
  const riskCap = equityCny * weeklyRiskPct(equityCny);
  if (!env.ACCOUNT_KV) {
    return { weekStartEquityCny: equityCny, weekLossCny: 0, weekRiskCny: riskCap, status: "KV未绑定，暂用当前权益作为本周基准" };
  }
  let baseline = Number(await env.ACCOUNT_KV.get(key));
  if (!Number.isFinite(baseline) || baseline <= 0) {
    baseline = equityCny;
    await env.ACCOUNT_KV.put(key, String(baseline));
  }
  return {
    weekStartEquityCny: baseline,
    weekLossCny: Math.max(0, baseline - equityCny),
    weekRiskCny: riskCap,
    status: "本周基准已同步",
  };
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: corsHeaders });
    try {
      for (const key of ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"]) {
        if (!env[key]) throw new Error(`Missing ${key}`);
      }
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
      const week = await weeklyLoss(env, equityCny);
      return jsonResponse({
        ok: true,
        updatedAt: new Date().toISOString(),
        equityUsdt,
        availableUsdt,
        equityCny,
        cnyRate: rateInfo.rate,
        cnyRateSource: rateInfo.source,
        ...week,
        position: parsePosition(positions, instruments),
      });
    } catch (error) {
      return jsonResponse({ ok: false, error: String(error) }, 500);
    }
  },
};
