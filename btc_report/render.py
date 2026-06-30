from __future__ import annotations

import html
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .advice import Advice
from .binance import MarketData
from .config import PositionConfig, PreferenceConfig
from .indicators import Indicators
from .macro_events import MacroBrief


CN_TZ = ZoneInfo("Asia/Shanghai")


def fmt_dt(value: datetime) -> str:
    return value.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M:%S")


def fmt_price(value: float | None) -> str:
    return "-" if value is None else f"{value:,.1f}"


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.2f}%"


def chart_points(data: MarketData) -> str:
    candles = (data.klines_15m or data.klines_1h or data.klines_4h)[-96:]
    values = [{"t": int(c["close_time"]), "p": round(c["close"], 2)} for c in candles]
    return json.dumps(values, ensure_ascii=False)


def render_report(
    generated_at: datetime,
    market: MarketData,
    indicators: Indicators,
    position: PositionConfig,
    preference: PreferenceConfig,
    advice: Advice,
    macro_brief: MacroBrief,
    archive_name: str,
) -> str:
    warnings = indicators.warnings + macro_brief.warnings + [x for x in [position.source_warning, preference.source_warning] if x]
    warning_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings) or "<li>数据源状态正常。</li>"
    actions_html = "".join(f"<li>{html.escape(item)}</li>" for item in advice.action_items)
    macro_events_html = "".join(
        "<li>"
        f"<strong>{html.escape(event.scheduled_at.astimezone(CN_TZ).strftime('%m-%d %H:%M'))} 北京时间 · {html.escape(event.title)}</strong>"
        f"<br><span class=\"small\">来源：<a href=\"{html.escape(event.url)}\">{html.escape(event.source)}</a> · "
        f"影响：{html.escape(event.impact)} · {html.escape(event.btc_view)}</span>"
        "</li>"
        for event in macro_brief.events
    ) or "<li>未来24小时未识别到已接入日历中的高影响事件。</li>"

    position_json = json.dumps(
        {
            "shortQty": position.short.quantity_btc,
            "shortEntry": position.short.entry_price,
            "shortStop": position.short.stop_loss,
            "shortTakeProfit": position.short.take_profit,
            "shortLeverage": position.short.leverage,
            "longQty": position.long.quantity_btc,
            "longEntry": position.long.entry_price,
            "liquidationPrice": position.liquidation_price,
            "accountEquity": position.account_equity_usdt,
            "maxSingleAddPct": preference.max_single_add_pct,
        },
        ensure_ascii=False,
    )
    points = chart_points(market)
    generated_text = fmt_dt(generated_at)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTC 永续合约 15分钟短线决策报告</title>
  <style>
    :root {{ --ink:#17202a; --muted:#667085; --line:#d9dee7; --bg:#f6f7f9; --panel:#fff; --accent:#0f766e; --danger:#b42318; --warn:#b45309; --good:#047857; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--ink); line-height:1.55; }}
    header {{ background:#102a43; color:#fff; padding:22px 16px 18px; }}
    main {{ width:min(1040px,100%); margin:0 auto; padding:14px; }}
    h1 {{ margin:0 0 8px; font-size:clamp(24px,6vw,40px); line-height:1.08; }}
    h2 {{ margin:0 0 12px; font-size:18px; }}
    .meta {{ color:#d7e4f2; font-size:14px; margin-top:4px; }}
    .grid {{ display:grid; grid-template-columns:repeat(12,1fr); gap:12px; }}
    section,.tile {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }}
    section {{ margin-bottom:12px; }}
    .span-4 {{ grid-column:span 4; }} .span-6 {{ grid-column:span 6; }}
    .hero {{ border-left:5px solid var(--accent); }}
    .headline {{ font-size:23px; font-weight:760; margin:0 0 10px; }}
    .pill {{ display:inline-flex; align-items:center; min-height:28px; border-radius:999px; padding:3px 10px; background:#e8f3f1; color:#0b635d; font-weight:700; font-size:13px; margin:0 6px 6px 0; }}
    .risk-high {{ background:#fee4e2; color:var(--danger); }} .risk-mid {{ background:#fef0c7; color:var(--warn); }} .risk-low {{ background:#dcfae6; color:var(--good); }}
    .label {{ color:var(--muted); font-size:13px; margin-bottom:3px; }}
    .value {{ font-size:21px; font-weight:760; overflow-wrap:anywhere; }}
    ul {{ padding-left:20px; margin:8px 0 0; }} li {{ margin:6px 0; }}
    canvas {{ width:100%; height:260px; display:block; }}
    .small {{ color:var(--muted); font-size:13px; }}
    .plan {{ border-left:4px solid #475467; }}
    footer {{ padding:18px 14px 30px; color:var(--muted); text-align:center; font-size:13px; }}
    @media (max-width:720px) {{ main {{ padding:10px; }} .grid {{ gap:10px; }} .span-4,.span-6 {{ grid-column:span 12; }} section,.tile {{ padding:12px; }} .headline {{ font-size:20px; }} canvas {{ height:220px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>BTC 永续合约 15分钟短线决策报告</h1>
    <div class="meta" id="liveHeaderMeta">正在从 OKX 获取最新行情 · 页面模板生成：{generated_text} 北京时间</div>
    <div class="meta" id="liveFetchMeta">实时抓取状态：等待浏览器执行</div>
  </header>
  <main>
    <section class="hero">
      <div class="headline">{html.escape(advice.headline)}</div>
      <span class="pill">方向：{html.escape(advice.bias)}</span>
      <span class="pill {'risk-high' if indicators.risk_level == '高' else 'risk-mid' if indicators.risk_level == '中' else 'risk-low'}">风险：{html.escape(indicators.risk_level)}</span>
      <span class="pill">趋势：{html.escape(indicators.trend)}</span>
      <p>{html.escape(advice.risk_summary)}</p>
      <ul>{actions_html}</ul>
    </section>

    <section>
      <h2>市场快照</h2>
      <div class="grid">
        <div class="tile span-4"><div class="label">最新标记价</div><div class="value" id="liveLatestPrice">{fmt_price(indicators.latest_price)}</div></div>
        <div class="tile span-4"><div class="label">15分钟涨跌</div><div class="value" id="liveChange15m">{fmt_pct(indicators.change_15m_pct)}</div></div>
        <div class="tile span-4"><div class="label">1小时涨跌</div><div class="value" id="liveChange1h">{fmt_pct(indicators.change_1h_pct)}</div></div>
        <div class="tile span-4"><div class="label">4小时涨跌</div><div class="value" id="liveChange4h">{fmt_pct(indicators.change_4h_pct)}</div></div>
        <div class="tile span-4"><div class="label">24小时涨跌</div><div class="value">{fmt_pct(indicators.change_24h_pct)}</div></div>
        <div class="tile span-4"><div class="label">资金费率</div><div class="value" id="liveFunding">{fmt_pct(indicators.funding_rate_pct)}</div></div>
        <div class="tile span-4"><div class="label">持仓量 BTC</div><div class="value" id="liveOpenInterest">{fmt_price(indicators.open_interest)}</div></div>
      </div>
    </section>

    <section>
      <h2>15分钟短线结构</h2>
      <canvas id="priceChart" width="960" height="300" aria-label="BTC 15分钟价格图"></canvas>
      <p class="small" id="liveStructure">短线支撑：{fmt_price(indicators.support)} · 短线阻力：{fmt_price(indicators.resistance)} · 15分钟波动：{fmt_pct(indicators.volatility_24h_pct)} · 成交量倍率：{indicators.volume_4h_ratio:.2f}x</p>
    </section>

    <section>
      <h2>当前仓位</h2>
      <p>{html.escape(advice.position_summary)}</p>
      <div class="grid">
        <div class="tile span-6"><div class="label">多头</div><div class="value">{position.long.quantity_btc:g} BTC @ {fmt_price(position.long.entry_price)}</div><div class="small">杠杆 {position.long.leverage:g}x · 止损 {fmt_price(position.long.stop_loss)} · 止盈 {fmt_price(position.long.take_profit)}</div></div>
        <div class="tile span-6"><div class="label">空头</div><div class="value">{position.short.quantity_btc:g} BTC @ {fmt_price(position.short.entry_price)}</div><div class="small">杠杆 {position.short.leverage:g}x · 止损 {fmt_price(position.short.stop_loss)} · 止盈 {fmt_price(position.short.take_profit)}</div></div>
        <div class="tile span-6"><div class="label">预估强平价</div><div class="value">{fmt_price(position.liquidation_price)}</div></div>
        <div class="tile span-6"><div class="label">当前仓位保证金</div><div class="value">{fmt_price(position.initial_margin_usdt)} USDT</div></div>
      </div>
    </section>

    <section class="plan">
      <h2>后续操作计划</h2>
      <p id="liveLongPlan">{html.escape(advice.long_plan)}</p>
      <p id="liveShortPlan">{html.escape(advice.short_plan)}</p>
      <p><strong>失效条件：</strong><span id="liveInvalidation">{html.escape(advice.invalidation)}</span></p>
      <p class="small">策略偏好：{html.escape(preference.style)}；单次加仓上限：账户权益的 {preference.max_single_add_pct * 100:.1f}%；总名义仓位上限：账户权益的 {preference.max_total_notional_pct * 100:.1f}%。</p>
    </section>

    <section>
      <h2>未来24小时宏观事件</h2>
      <p>{html.escape(macro_brief.summary)}</p>
      <p><strong>BTC波动预测：</strong>{html.escape(macro_brief.forecast)}</p>
      <p class="small">窗口：{macro_brief.window_start:%Y-%m-%d %H:%M} - {macro_brief.window_end:%Y-%m-%d %H:%M} 北京时间</p>
      <ul>{macro_events_html}</ul>
    </section>

    <section>
      <h2>运行状态</h2>
      <ul id="liveStatus">{warning_html}</ul>
      <p class="small">本网页仅作投资决策辅助，不自动交易，不构成收益承诺。</p>
    </section>
  </main>
  <footer>Generated by GitHub Actions · BTC-USDT Perpetual Futures Report</footer>
  <script>
    const points = {points};
    const positionConfig = {position_json};
    const canvas = document.getElementById('priceChart');
    const ctx = canvas.getContext('2d');
    function drawChart() {{
      const w = canvas.width, h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = '#d9dee7';
      ctx.lineWidth = 1;
      for (let i = 0; i < 5; i++) {{
        const y = 20 + i * ((h - 44) / 4);
        ctx.beginPath(); ctx.moveTo(48, y); ctx.lineTo(w - 12, y); ctx.stroke();
      }}
      if (!points.length) return;
      const prices = points.map(p => p.p);
      const min = Math.min(...prices), max = Math.max(...prices);
      const pad = Math.max((max - min) * 0.08, 1);
      const lo = min - pad, hi = max + pad;
      const x = i => 48 + i * ((w - 68) / Math.max(points.length - 1, 1));
      const y = p => 20 + (hi - p) * ((h - 44) / (hi - lo));
      ctx.strokeStyle = '#0f766e'; ctx.lineWidth = 3; ctx.beginPath();
      points.forEach((p, i) => {{ if (i === 0) ctx.moveTo(x(i), y(p.p)); else ctx.lineTo(x(i), y(p.p)); }});
      ctx.stroke();
    }}
    drawChart();
    const fmtPrice = value => Number.isFinite(value) ? value.toLocaleString('en-US', {{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}) : '-';
    const fmtPct = value => Number.isFinite(value) ? `${{value >= 0 ? '+' : ''}}${{value.toFixed(2)}}%` : '-';
    const fmtTime = value => {{
      const pad = number => String(number).padStart(2, '0');
      return `${{value.getFullYear()}}-${{pad(value.getMonth() + 1)}}-${{pad(value.getDate())}} ${{pad(value.getHours())}}:${{pad(value.getMinutes())}}:${{pad(value.getSeconds())}}`;
    }};
    const pct = (a, b) => b ? (a / b - 1) * 100 : 0;
    const setText = (id, text) => {{ const el = document.getElementById(id); if (el) el.textContent = text; }};
    const okxUrl = path => `https://www.okx.com${{path}}${{path.includes('?') ? '&' : '?'}}_=${{Date.now()}}`;
    async function fetchJson(label, path) {{
      const response = await fetch(okxUrl(path), {{ cache: 'no-store' }});
      if (!response.ok) throw new Error(`${{label}} HTTP ${{response.status}}`);
      const payload = await response.json();
      if (payload.code && payload.code !== '0') throw new Error(`${{label}} code ${{payload.code}}: ${{payload.msg || ''}}`);
      return payload;
    }}
    async function fetchJsonSoft(label, path) {{
      try {{
        return {{ ok: true, label, payload: await fetchJson(label, path) }};
      }} catch (error) {{
        return {{ ok: false, label, error: String(error) }};
      }}
    }}
    function parseCandles(rows) {{
      return rows.slice().reverse().map(row => ({{ high:Number(row[2]), low:Number(row[3]), close:Number(row[4]), quoteVolume:Number(row[7] || 0) }}));
    }}
    function lastItem(items) {{
      return items && items.length ? items[items.length - 1] : null;
    }}
    function nearestShortStop(latest, resistance) {{
      const candidates = [resistance * 1.003, latest * 1.006];
      if (positionConfig.liquidationPrice) candidates.push(positionConfig.liquidationPrice * 0.997);
      return Math.min(...candidates.filter(v => v > latest));
    }}
    function nearestLongStop(latest, support) {{
      const candidates = [support * 0.997, latest * 0.994];
      if (positionConfig.liquidationPrice) candidates.push(positionConfig.liquidationPrice * 1.003);
      return Math.max(...candidates.filter(v => v < latest));
    }}
    async function refreshLiveMarket(reason = 'page-load') {{
      try {{
        setText('liveFetchMeta', `实时抓取状态：正在请求 OKX · ${{fmtTime(new Date())}}`);
        const [c15j, c1hj, c4hj, fundingResult, oiResult, mj] = await Promise.all([
          fetchJson('15m candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=96'),
          fetchJson('1h candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1H&limit=24'),
          fetchJson('4h candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=4H&limit=8'),
          fetchJsonSoft('funding', '/api/v5/public/funding-rate?instId=BTC-USDT-SWAP'),
          fetchJsonSoft('open interest', '/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP'),
          fetchJson('mark price', '/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP')
        ]);
        const c15 = parseCandles(c15j.data || []);
        const c1h = parseCandles(c1hj.data || []);
        const c4h = parseCandles(c4hj.data || []);
        const markRow = mj.data && mj.data.length ? mj.data[0] : null;
        const latestCandle = lastItem(c15);
        const latest = Number((markRow && markRow.markPx) || (latestCandle && latestCandle.close) || 0);
        const support = Math.min(...c15.slice(-24).map(c => c.low));
        const resistance = Math.max(...c15.slice(-24).map(c => c.high));
        const fundingPayload = fundingResult.ok ? fundingResult.payload : {{}};
        const oiPayload = oiResult.ok ? oiResult.payload : {{}};
        const fundingRow = fundingPayload.data && fundingPayload.data.length ? fundingPayload.data[0] : null;
        const oiRow = oiPayload.data && oiPayload.data.length ? oiPayload.data[0] : null;
        const funding = fundingRow ? Number(fundingRow.fundingRate || 0) * 100 : NaN;
        const openInterest = oiRow ? Number(oiRow.oiCcy || 0) : NaN;
        const returns = c15.slice(1).map((c, i) => pct(c.close, c15[i].close));
        const avg = returns.reduce((a, b) => a + b, 0) / Math.max(returns.length, 1);
        const vol = Math.sqrt(returns.reduce((a, b) => a + (b - avg) ** 2, 0) / Math.max(returns.length, 1));
        const volumeSlice = c15.slice(-33, -1);
        const volumeBase = volumeSlice.reduce((a, c) => a + c.quoteVolume, 0) / Math.max(volumeSlice.length, 1);
        const volumeRatio = volumeBase && latestCandle ? latestCandle.quoteVolume / volumeBase : 1;
        const shortStop = positionConfig.shortStop || nearestShortStop(latest, resistance);
        const shortTp1 = Math.min(latest * 0.988, (support + resistance) / 2);
        const shortTp2 = support;
        const longTrigger = Math.max(resistance, latest * 1.002);
        const longStop = nearestLongStop(latest, support);
        const longTp1 = longTrigger * 1.006;
        const longTp2 = longTrigger * 1.014;
        const addBudget = positionConfig.accountEquity * positionConfig.maxSingleAddPct;

        setText('liveLatestPrice', fmtPrice(latest));
        setText('liveChange15m', fmtPct(pct(latest, c15.length >= 2 ? c15[c15.length - 2].close : latest)));
        setText('liveChange1h', fmtPct(pct(latest, c1h.length >= 2 ? c1h[c1h.length - 2].close : latest)));
        setText('liveChange4h', fmtPct(pct(latest, c4h.length >= 2 ? c4h[c4h.length - 2].close : latest)));
        setText('liveFunding', fmtPct(funding));
        setText('liveOpenInterest', fmtPrice(openInterest));
        setText('liveStructure', `短线支撑：${{fmtPrice(support)}} · 短线阻力：${{fmtPrice(resistance)}} · 15分钟波动：${{fmtPct(vol)}} · 成交量倍率：${{volumeRatio.toFixed(2)}}x · 数据：浏览器现场抓取`);
        setText('liveLongPlan', `多头计划：只有在15分钟收盘站上 ${{fmtPrice(resistance)}}，或回踩 ${{fmtPrice(support * 0.998)}} - ${{fmtPrice(support * 1.002)}} 后重新放量上行，才考虑做多；单次新增名义仓位不超过 ${{fmtPrice(addBudget)}} USDT。止损 ${{fmtPrice(longStop)}}，止盈分两档：${{fmtPrice(longTp1)}} / ${{fmtPrice(longTp2)}}。`);
        setText('liveShortPlan', `空头计划：已有空单 ${{positionConfig.shortQty}} BTC，开仓均价 ${{fmtPrice(positionConfig.shortEntry)}}。若价格反弹到 ${{fmtPrice(resistance * 0.998)}} - ${{fmtPrice(resistance * 1.002)}} 受阻，可继续持有；不建议在强平价附近继续加空。必须设置硬止损 ${{fmtPrice(shortStop)}}，第一止盈 ${{fmtPrice(shortTp1)}}，第二止盈 ${{fmtPrice(shortTp2)}}。若跌破 ${{fmtPrice(shortTp1)}} 后反抽不破，可把止损下移到开仓价 ${{fmtPrice(positionConfig.shortEntry)}} 附近。`);
        setText('liveInvalidation', `空头失效：15分钟收盘突破 ${{fmtPrice(resistance)}} 或触发止损 ${{fmtPrice(shortStop)}}；多头失效：15分钟收盘跌破 ${{fmtPrice(support)}} 或触发止损 ${{fmtPrice(longStop)}}。`);
        setText('liveHeaderMeta', `本次刷新：${{fmtTime(new Date())}} 北京时间 · 标的：BTCUSDT · 数据源：OKX 浏览器现场抓取`);
        const softWarnings = [fundingResult, oiResult].filter(item => !item.ok).map(item => `${{item.label}}失败：${{item.error}}`);
        setText('liveFetchMeta', `实时抓取状态：成功 · OKX标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}}${{softWarnings.length ? ' · 部分数据缺失：' + softWarnings.join('；') : ''}}`);
        const status = document.getElementById('liveStatus');
        if (status) status.innerHTML = `<li>本次页面刷新已现场获取 OKX 行情；触发方式：${{reason}}</li>${{softWarnings.map(item => `<li>${{item}}</li>`).join('')}}`;
      }} catch (error) {{
        setText('liveFetchMeta', `实时抓取状态：失败 · ${{String(error)}} · ${{fmtTime(new Date())}}`);
        const status = document.getElementById('liveStatus');
        if (status) status.innerHTML = `<li>浏览器实时行情刷新失败：${{String(error)}}</li>`;
      }}
    }}
    refreshLiveMarket('page-load');
    document.addEventListener('visibilitychange', () => {{ if (document.visibilityState === 'visible') refreshLiveMarket('page-visible'); }});
    window.addEventListener('focus', () => refreshLiveMarket('window-focus'));
  </script>
</body>
</html>
"""
