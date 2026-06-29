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


def fmt_price(value: float | None) -> str:
    return "-" if value is None else f"{value:,.1f}"


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:+.2f}%"


def chart_points(data: MarketData) -> str:
    candles = (data.klines_15m or data.klines_1h or data.klines_4h)[-96:]
    if not candles:
        return "[]"
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
    generated_cn = generated_at.astimezone(CN_TZ)
    warnings = indicators.warnings + macro_brief.warnings + [x for x in [position.source_warning, preference.source_warning] if x]
    warning_html = "".join(f"<li>{html.escape(w)}</li>" for w in warnings) or "<li>数据源状态正常。</li>"
    actions_html = "".join(f"<li>{html.escape(item)}</li>" for item in advice.action_items)
    if macro_brief.events:
        macro_events_html = "".join(
            "<li>"
            f"<strong>{html.escape(event.scheduled_at.astimezone(CN_TZ).strftime('%m-%d %H:%M'))} 北京时间 · "
            f"{html.escape(event.title)}</strong>"
            f"<br><span class=\"small\">来源：<a href=\"{html.escape(event.url)}\">{html.escape(event.source)}</a> · "
            f"影响：{html.escape(event.impact)} · {html.escape(event.btc_view)}</span>"
            "</li>"
            for event in macro_brief.events
        )
    else:
        macro_events_html = "<li>未来24小时未识别到已接入日历中的高影响事件。</li>"
    points = chart_points(market)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BTC 永续合约 15分钟短线决策报告</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #667085;
      --line: #d9dee7;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --accent: #0f766e;
      --warn: #b45309;
      --danger: #b42318;
      --good: #047857;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.55;
    }}
    header {{
      background: #102a43;
      color: #fff;
      padding: 22px 16px 18px;
    }}
    main {{
      width: min(1040px, 100%);
      margin: 0 auto;
      padding: 14px;
    }}
    h1 {{ margin: 0 0 8px; font-size: clamp(24px, 6vw, 40px); line-height: 1.08; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    .meta {{ color: #d7e4f2; font-size: 14px; }}
    .grid {{ display: grid; grid-template-columns: repeat(12, 1fr); gap: 12px; }}
    section, .tile {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }}
    section {{ margin-bottom: 12px; }}
    .span-12 {{ grid-column: span 12; }}
    .span-6 {{ grid-column: span 6; }}
    .span-4 {{ grid-column: span 4; }}
    .hero {{
      border-left: 5px solid var(--accent);
    }}
    .headline {{ font-size: 23px; font-weight: 760; margin: 0 0 10px; }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 3px 10px;
      background: #e8f3f1;
      color: #0b635d;
      font-weight: 700;
      font-size: 13px;
      margin: 0 6px 6px 0;
      white-space: nowrap;
    }}
    .risk-high {{ background: #fee4e2; color: var(--danger); }}
    .risk-mid {{ background: #fef0c7; color: var(--warn); }}
    .risk-low {{ background: #dcfae6; color: var(--good); }}
    .label {{ color: var(--muted); font-size: 13px; margin-bottom: 3px; }}
    .value {{ font-size: 21px; font-weight: 760; overflow-wrap: anywhere; }}
    ul {{ padding-left: 20px; margin: 8px 0 0; }}
    li {{ margin: 6px 0; }}
    canvas {{ width: 100%; height: 260px; display: block; }}
    .small {{ color: var(--muted); font-size: 13px; }}
    .plan {{ border-left: 4px solid #475467; }}
    footer {{ padding: 18px 14px 30px; color: var(--muted); text-align: center; font-size: 13px; }}
    @media (max-width: 720px) {{
      main {{ padding: 10px; }}
      .grid {{ gap: 10px; }}
      .span-6, .span-4 {{ grid-column: span 12; }}
      section, .tile {{ padding: 12px; }}
      .headline {{ font-size: 20px; }}
      canvas {{ height: 220px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="meta" id="nodeCountdown">下次节点刷新倒计时：--:--</div>
    <h1>BTC 永续合约 15分钟短线决策报告</h1>
    <div class="meta" id="liveHeaderMeta">页面生成时间：{generated_cn:%Y-%m-%d %H:%M} 北京时间 · 标的：{html.escape(market.symbol)} · 数据源：{html.escape(market.source)} · 归档：{html.escape(archive_name)}</div>
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
        <div class="tile span-4"><div class="label">24小时区间</div><div class="value">{fmt_price(indicators.low_24h)} / {fmt_price(indicators.high_24h)}</div></div>
        <div class="tile span-4"><div class="label">资金费率</div><div class="value" id="liveFunding">{fmt_pct(indicators.funding_rate_pct)}</div></div>
        <div class="tile span-4"><div class="label">持仓量 BTC</div><div class="value" id="liveOpenInterest">{fmt_price(indicators.open_interest)}</div></div>
      </div>
    </section>

    <section>
      <h2>15分钟短线结构</h2>
      <canvas id="priceChart" width="960" height="300" aria-label="BTC 15分钟价格图"></canvas>
      <p class="small" id="liveStructure">短线支撑：{fmt_price(indicators.support)} · 短线阻力：{fmt_price(indicators.resistance)} · 15分钟波动：{fmt_pct(indicators.volatility_24h_pct)} · 成交量倍率：{indicators.volume_4h_ratio:.2f}x · 基差：{fmt_pct(indicators.basis_pct)}</p>
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
    const positionConfig = {json.dumps({
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
    }, ensure_ascii=False)};
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
      if (!points.length) {{
        ctx.fillStyle = '#667085'; ctx.font = '18px sans-serif'; ctx.fillText('暂无价格数据', 48, 80); return;
      }}
      const prices = points.map(p => p.p);
      const min = Math.min(...prices), max = Math.max(...prices);
      const pad = Math.max((max - min) * 0.08, 1);
      const lo = min - pad, hi = max + pad;
      const x = i => 48 + i * ((w - 68) / Math.max(points.length - 1, 1));
      const y = p => 20 + (hi - p) * ((h - 44) / (hi - lo));
      ctx.strokeStyle = '#0f766e'; ctx.lineWidth = 3; ctx.beginPath();
      points.forEach((p, i) => {{ if (i === 0) ctx.moveTo(x(i), y(p.p)); else ctx.lineTo(x(i), y(p.p)); }});
      ctx.stroke();
      ctx.fillStyle = '#17202a'; ctx.font = '15px sans-serif';
      ctx.fillText(hi.toFixed(0), 4, 28);
      ctx.fillText(lo.toFixed(0), 4, h - 18);
      ctx.fillStyle = '#0f766e';
      ctx.beginPath(); ctx.arc(x(points.length - 1), y(points[points.length - 1].p), 5, 0, Math.PI * 2); ctx.fill();
    }}
    drawChart();
    const fmtPrice = value => Number.isFinite(value) ? value.toLocaleString('en-US', {{ minimumFractionDigits: 1, maximumFractionDigits: 1 }}) : '-';
    const fmtPctJs = value => Number.isFinite(value) ? `${{value >= 0 ? '+' : ''}}${{value.toFixed(2)}}%` : '-';
    const pct = (a, b) => b ? (a / b - 1) * 100 : 0;
    const setText = (id, text) => {{ const el = document.getElementById(id); if (el) el.textContent = text; }};
    function parseOkxCandles(rows) {{
      return rows.slice().reverse().map(row => ({{
        open: Number(row[1]), high: Number(row[2]), low: Number(row[3]), close: Number(row[4]),
        quoteVolume: Number(row[7] || 0), close_time: Number(row[0]), p: Number(row[4])
      }}));
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
    let liveRefreshTimer = null;
    let countdownTimer = null;
    let lastLiveBucket = '';
    function currentQuarterBucket() {{
      const now = new Date();
      const quarter = Math.floor(now.getMinutes() / 15) * 15;
      return `${{now.getFullYear()}}-${{now.getMonth() + 1}}-${{now.getDate()}} ${{
        String(now.getHours()).padStart(2, '0')
      }}:${{String(quarter).padStart(2, '0')}}`;
    }}
    function nextQuarterDelayMs() {{
      const now = new Date();
      const next = new Date(now);
      const nextMinute = Math.floor(now.getMinutes() / 15) * 15 + 15;
      next.setSeconds(3, 0);
      if (nextMinute >= 60) {{
        next.setHours(next.getHours() + 1, 0, 3, 0);
      }} else {{
        next.setMinutes(nextMinute, 3, 0);
      }}
      return Math.max(next.getTime() - now.getTime(), 15000);
    }}
    function nextQuarterTime() {{
      const now = new Date();
      const next = new Date(now);
      const nextMinute = Math.floor(now.getMinutes() / 15) * 15 + 15;
      next.setSeconds(3, 0);
      if (nextMinute >= 60) {{
        next.setHours(next.getHours() + 1, 0, 3, 0);
      }} else {{
        next.setMinutes(nextMinute, 3, 0);
      }}
      return next;
    }}
    function updateCountdown() {{
      const target = nextQuarterTime();
      const diff = Math.max(target.getTime() - Date.now(), 0);
      const minutes = Math.floor(diff / 60000);
      const seconds = Math.floor((diff % 60000) / 1000);
      const text = `下次节点刷新倒计时：${{String(minutes).padStart(2, '0')}}:${{String(seconds).padStart(2, '0')}} · 目标：${{target.toLocaleTimeString('zh-CN', {{ hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }})}}`;
      setText('nodeCountdown', text);
    }}
    function startCountdown() {{
      if (countdownTimer) clearInterval(countdownTimer);
      updateCountdown();
      countdownTimer = setInterval(updateCountdown, 1000);
    }}
    function scheduleNextQuarterRefresh() {{
      if (liveRefreshTimer) clearTimeout(liveRefreshTimer);
      liveRefreshTimer = setTimeout(async () => {{
        await refreshLiveMarket('quarter-node');
        scheduleNextQuarterRefresh();
      }}, nextQuarterDelayMs());
    }}
    async function refreshLiveMarket(reason = 'manual') {{
      try {{
        const [c15r, c1hr, c4hr, fr, oi, mark] = await Promise.all([
          fetch('https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=96'),
          fetch('https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1H&limit=24'),
          fetch('https://www.okx.com/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=4H&limit=8'),
          fetch('https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP'),
          fetch('https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP'),
          fetch('https://www.okx.com/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP')
        ]);
        const [c15j, c1hj, c4hj, fj, oij, mj] = await Promise.all([c15r.json(), c1hr.json(), c4hr.json(), fr.json(), oi.json(), mark.json()]);
        const c15 = parseOkxCandles(c15j.data || []);
        const c1h = parseOkxCandles(c1hj.data || []);
        const c4h = parseOkxCandles(c4hj.data || []);
        const latest = Number(mj.data?.[0]?.markPx || c15.at(-1)?.close || 0);
        const support = Math.min(...c15.slice(-24).map(c => c.low));
        const resistance = Math.max(...c15.slice(-24).map(c => c.high));
        const funding = Number(fj.data?.[0]?.fundingRate || 0) * 100;
        const openInterest = Number(oij.data?.[0]?.oiCcy || 0);
        const returns = c15.slice(1).map((c, i) => pct(c.close, c15[i].close));
        const avg = returns.reduce((a, b) => a + b, 0) / Math.max(returns.length, 1);
        const variance = returns.reduce((a, b) => a + (b - avg) ** 2, 0) / Math.max(returns.length, 1);
        const vol = Math.sqrt(variance);
        const volumeBase = c15.slice(-33, -1).reduce((a, c) => a + c.quoteVolume, 0) / Math.max(c15.slice(-33, -1).length, 1);
        const volumeRatio = volumeBase ? c15.at(-1).quoteVolume / volumeBase : 1;
        const shortStop = positionConfig.shortStop || nearestShortStop(latest, resistance);
        const shortTp1 = Math.min(latest * 0.988, (support + resistance) / 2);
        const shortTp2 = support;
        const longTrigger = Math.max(resistance, latest * 1.002);
        const longStop = nearestLongStop(latest, support);
        const longTp1 = longTrigger * 1.006;
        const longTp2 = longTrigger * 1.014;
        const addBudget = positionConfig.accountEquity * positionConfig.maxSingleAddPct;

        setText('liveLatestPrice', fmtPrice(latest));
        setText('liveChange15m', fmtPctJs(pct(latest, c15.at(-2)?.close || latest)));
        setText('liveChange1h', fmtPctJs(pct(latest, c1h.at(-2)?.close || latest)));
        setText('liveChange4h', fmtPctJs(pct(latest, c4h.at(-2)?.close || latest)));
        setText('liveFunding', fmtPctJs(funding));
        setText('liveOpenInterest', fmtPrice(openInterest));
        setText('liveStructure', `短线支撑：${{fmtPrice(support)}} · 短线阻力：${{fmtPrice(resistance)}} · 15分钟波动：${{fmtPctJs(vol)}} · 成交量倍率：${{volumeRatio.toFixed(2)}}x · 数据：浏览器实时刷新`);
        setText('liveLongPlan', `多头计划：只有在15分钟收盘站上 ${{fmtPrice(resistance)}}，或回踩 ${{fmtPrice(support * 0.998)}} - ${{fmtPrice(support * 1.002)}} 后重新放量上行，才考虑做多；单次新增名义仓位不超过 ${{fmtPrice(addBudget)}} USDT。止损 ${{fmtPrice(longStop)}}，止盈分两档：${{fmtPrice(longTp1)}} / ${{fmtPrice(longTp2)}}。`);
        setText('liveShortPlan', `空头计划：已有空单 ${{positionConfig.shortQty}} BTC，开仓均价 ${{fmtPrice(positionConfig.shortEntry)}}。若价格反弹到 ${{fmtPrice(resistance * 0.998)}} - ${{fmtPrice(resistance * 1.002)}} 受阻，可继续持有；不建议在强平价附近继续加空。必须设置硬止损 ${{fmtPrice(shortStop)}}，第一止盈 ${{fmtPrice(shortTp1)}}，第二止盈 ${{fmtPrice(shortTp2)}}。若跌破 ${{fmtPrice(shortTp1)}} 后反抽不破，可把止损下移到开仓价 ${{fmtPrice(positionConfig.shortEntry)}} 附近。`);
        setText('liveInvalidation', `空头失效：15分钟收盘突破 ${{fmtPrice(resistance)}} 或触发止损 ${{fmtPrice(shortStop)}}；多头失效：15分钟收盘跌破 ${{fmtPrice(support)}} 或触发止损 ${{fmtPrice(longStop)}}。`);
        const bucket = currentQuarterBucket();
        lastLiveBucket = bucket;
        setText('liveHeaderMeta', `节点刷新：${{bucket}} 北京时间 · 实时执行：${{new Date().toLocaleString('zh-CN', {{ hour12: false }})}} · 标的：BTCUSDT · 数据源：OKX 浏览器实时行情`);
        const status = document.getElementById('liveStatus');
        if (status) status.innerHTML = `<li>浏览器已按节点刷新 OKX 行情：${{bucket}} 北京时间；触发方式：${{reason}}</li>`;
      }} catch (error) {{
        const status = document.getElementById('liveStatus');
        if (status) status.innerHTML = `<li>浏览器实时行情刷新失败：${{String(error)}}</li>`;
      }}
    }}
    refreshLiveMarket('page-load');
    startCountdown();
    scheduleNextQuarterRefresh();
    document.addEventListener('visibilitychange', () => {{
      if (document.visibilityState === 'visible' && currentQuarterBucket() !== lastLiveBucket) {{
        refreshLiveMarket('page-visible');
        startCountdown();
        scheduleNextQuarterRefresh();
      }}
    }});
    window.addEventListener('focus', () => {{
      if (currentQuarterBucket() !== lastLiveBucket) {{
        refreshLiveMarket('window-focus');
        startCountdown();
        scheduleNextQuarterRefresh();
      }}
    }});
  </script>
</body>
</html>
"""
