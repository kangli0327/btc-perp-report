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


def fmt_money(value: float | None) -> str:
    return "-" if value is None else f"{value:+,.2f}"


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
        + (f"<br><span class=\"small\"><strong>市场预期：</strong>{html.escape(event.expected)}</span>" if event.expected else "")
        + (f"<br><span class=\"small\"><strong>前值：</strong>{html.escape(event.previous)}</span>" if event.previous else "")
        + (f"<br><span class=\"small\"><strong>我的判断：</strong>{html.escape(event.my_forecast)}</span>" if event.my_forecast else "")
        + (f"<br><span class=\"small\"><strong>BTC方向：</strong>{html.escape(event.btc_direction)}</span>" if event.btc_direction else "")
        + "</li>"
        for event in macro_brief.events
    ) or "<li>未来24小时未识别到已接入日历中的高影响事件。</li>"

    has_short = position.short.quantity_btc > 0
    has_long = position.long.quantity_btc > 0
    active_side = "short" if has_short else "long" if has_long else "flat"
    active_qty = position.short.quantity_btc if active_side == "short" else position.long.quantity_btc if active_side == "long" else 0.0
    active_entry = position.short.entry_price if active_side == "short" else position.long.entry_price if active_side == "long" else 0.0
    active_leverage = position.short.leverage if active_side == "short" else position.long.leverage if active_side == "long" else 1.0
    latest_price = indicators.latest_price
    if active_side == "short":
        initial_pnl = (active_entry - latest_price) * active_qty
    elif active_side == "long":
        initial_pnl = (latest_price - active_entry) * active_qty
    else:
        initial_pnl = 0.0
    initial_roi = initial_pnl / position.initial_margin_usdt * 100 if position.initial_margin_usdt else 0.0
    initial_notional = active_qty * latest_price
    maintenance_margin = max(initial_notional * 0.004, 1.0)
    maintenance_ratio = (position.initial_margin_usdt + initial_pnl) / maintenance_margin * 100 if maintenance_margin else 0.0
    if position.liquidation_price and active_side == "short":
        liq_gap = (position.liquidation_price / latest_price - 1) * 100
    elif position.liquidation_price and active_side == "long":
        liq_gap = (1 - position.liquidation_price / latest_price) * 100
    else:
        liq_gap = 0.0
    liq_state = "危险" if position.liquidation_price and liq_gap < 1.2 else "偏紧" if position.liquidation_price and liq_gap < 3 else "正常"

    position_json = json.dumps(
        {
            "activeSide": active_side,
            "activeQty": active_qty,
            "activeEntry": active_entry,
            "activeLeverage": active_leverage,
            "initialMargin": position.initial_margin_usdt,
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
    .position-card {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:16px; margin-bottom:12px; }}
    .position-head {{ display:grid; grid-template-columns:1fr auto; gap:14px; align-items:start; margin-bottom:24px; }}
    .contract-title {{ font-size:28px; line-height:1.1; font-weight:780; color:#0b0f14; white-space:nowrap; }}
    .chevron {{ color:#98a2b3; font-weight:500; margin-left:4px; }}
    .pos-badges {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:10px; }}
    .okx-badge {{ min-height:32px; border-radius:7px; padding:3px 10px; background:#f1f3f5; color:#20242a; font-size:21px; line-height:1.2; }}
    .okx-badge.side-short {{ background:#ffd1e2; color:#87224d; }}
    .okx-badge.side-long {{ background:#cdfae3; color:#05603a; }}
    .signal-bars {{ display:inline-flex; gap:4px; align-items:center; height:32px; }}
    .signal-bars span {{ width:4px; height:22px; border-radius:2px; background:#e5e7eb; }}
    .signal-bars span:first-child {{ background:#2e7d32; }}
    .pnl-box {{ text-align:right; min-width:156px; }}
    .pnl-label {{ color:#8a8f98; font-size:22px; text-decoration:underline dashed #858b94 2px; text-underline-offset:6px; white-space:nowrap; }}
    .pnl-value {{ margin-top:8px; font-size:27px; line-height:1.1; font-weight:780; color:#2e7d32; white-space:nowrap; }}
    .pnl-value.loss {{ color:#b42318; }}
    .position-grid {{ display:grid; grid-template-columns:repeat(3,1fr); column-gap:28px; row-gap:28px; }}
    .okx-label {{ color:#8a8f98; font-size:22px; line-height:1.15; text-decoration:underline dashed #858b94 2px; text-underline-offset:6px; }}
    .okx-value {{ margin-top:9px; font-size:27px; line-height:1.1; font-weight:520; color:#101318; overflow-wrap:anywhere; }}
    .margin-inline {{ display:inline-flex; align-items:center; gap:8px; }}
    .plus-dot {{ display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border:2px solid #111; border-radius:50%; font-size:20px; line-height:20px; font-weight:800; }}
    .liq-note {{ margin-top:18px; padding:10px 12px; border-radius:8px; background:#f8fafc; color:#475467; font-size:14px; }}
    .liq-note.danger {{ background:#fee4e2; color:#b42318; }}
    .liq-note.warn {{ background:#fef0c7; color:#b45309; }}
    ul {{ padding-left:20px; margin:8px 0 0; }} li {{ margin:6px 0; }}
    canvas {{ width:100%; height:260px; display:block; }}
    .small {{ color:var(--muted); font-size:13px; }}
    .plan {{ border-left:4px solid #475467; }}
    footer {{ padding:18px 14px 30px; color:var(--muted); text-align:center; font-size:13px; }}
    @media (max-width:720px) {{ main {{ padding:10px; }} .grid {{ gap:10px; }} .span-4,.span-6 {{ grid-column:span 12; }} section,.tile {{ padding:12px; }} .headline {{ font-size:20px; }} canvas {{ height:220px; }} .position-card {{ padding:14px; }} .position-head {{ gap:8px; margin-bottom:20px; }} .contract-title {{ font-size:25px; }} .okx-badge {{ font-size:19px; min-height:30px; padding:3px 9px; }} .pnl-box {{ min-width:136px; }} .pnl-label,.okx-label {{ font-size:18px; }} .pnl-value,.okx-value {{ font-size:23px; }} .position-grid {{ column-gap:14px; row-gap:24px; }} }}
    @media (max-width:430px) {{ .contract-title {{ font-size:23px; }} .position-head {{ grid-template-columns:1fr; }} .pnl-box {{ text-align:left; }} .position-grid {{ grid-template-columns:repeat(2,1fr); }} }}
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
      <div class="position-card">
        <div class="position-head">
          <div>
            <div class="contract-title">BTCUSDT 永续 <span class="chevron">›</span></div>
            <div class="pos-badges">
              <span class="okx-badge {'side-short' if active_side == 'short' else 'side-long' if active_side == 'long' else ''}" id="positionSideBadge">{'空' if active_side == 'short' else '多' if active_side == 'long' else '无仓'}</span>
              <span class="okx-badge">逐仓</span>
              <span class="okx-badge" id="positionLeverage">{active_leverage:g}x</span>
              <span class="signal-bars" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></span>
            </div>
          </div>
          <div class="pnl-box">
            <div class="pnl-label">收益额 (USDT)</div>
            <div class="pnl-value {'loss' if initial_pnl < 0 else ''}" id="positionPnl">{fmt_money(initial_pnl)} ({fmt_pct(initial_roi)})</div>
          </div>
        </div>
        <div class="position-grid">
          <div>
            <div class="okx-label">持仓量 (BTC)</div>
            <div class="okx-value" id="positionQty">{active_qty:g}</div>
          </div>
          <div>
            <div class="okx-label">保证金 (USDT)</div>
            <div class="okx-value margin-inline"><span id="positionMargin">{fmt_price(position.initial_margin_usdt)}</span><span class="plus-dot">+</span></div>
          </div>
          <div>
            <div class="okx-label">维持保证金率</div>
            <div class="okx-value" id="positionMmr">{maintenance_ratio:.2f}%</div>
          </div>
          <div>
            <div class="okx-label">开仓均价</div>
            <div class="okx-value" id="positionEntry">{fmt_price(active_entry)}</div>
          </div>
          <div>
            <div class="okx-label">标记价格</div>
            <div class="okx-value" id="positionMarkPrice">{fmt_price(latest_price)}</div>
          </div>
          <div>
            <div class="okx-label">预估强平价</div>
            <div class="okx-value" id="positionLiqPrice">{fmt_price(position.liquidation_price)}</div>
          </div>
        </div>
        <div class="liq-note {'danger' if liq_state == '危险' else 'warn' if liq_state == '偏紧' else ''}" id="positionLiqState">强平状态：{liq_state} · 距离强平约 {liq_gap:.2f}% · {html.escape(advice.position_summary)}</div>
      </div>
    </section>

    <section class="plan">
      <h2>后续操作计划</h2>
      <p><strong>当前点位：</strong><span id="simpleCurrentPoint">{fmt_price(indicators.latest_price)}</span></p>
      <p><strong>止盈点位：</strong><span id="simpleTakeProfit">{fmt_price(indicators.latest_price * 0.988)} - {fmt_price(indicators.support)} - {fmt_price(indicators.support * 0.965)} 分批止盈</span></p>
      <p><strong>止损点位：</strong><span id="simpleStopLoss">{fmt_price(indicators.resistance * 1.002)} 附近硬止损，接近强平前必须离场</span></p>
      <p><strong>加空点位：</strong><span id="simpleShortEntry">{fmt_price(indicators.resistance * 0.998)} - {fmt_price(indicators.resistance * 1.002)} 反弹受阻再考虑</span></p>
      <p><strong>开多点位：</strong><span id="simpleLongEntry">{fmt_price(indicators.support)} - {fmt_price(indicators.support * 0.985)} 分批开多</span></p>
      <p><strong>参考信息：</strong><span id="simplePlanContext">支撑 {fmt_price(indicators.support)} · 阻力 {fmt_price(indicators.resistance)} · 强平 {fmt_price(position.liquidation_price)}</span></p>
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
    function updatePositionUi(latest) {{
      const side = positionConfig.activeSide;
      const qty = Number(positionConfig.activeQty || 0);
      const entry = Number(positionConfig.activeEntry || 0);
      const margin = Number(positionConfig.initialMargin || 0);
      const liq = Number(positionConfig.liquidationPrice || 0);
      let pnl = 0;
      if (side === 'short') pnl = (entry - latest) * qty;
      if (side === 'long') pnl = (latest - entry) * qty;
      const roi = margin ? pnl / margin * 100 : 0;
      const notional = Math.abs(qty * latest);
      const maintenanceMargin = Math.max(notional * 0.004, 1);
      const marginRatio = maintenanceMargin ? (margin + pnl) / maintenanceMargin * 100 : 0;
      let liqGap = 0;
      if (liq && side === 'short') liqGap = (liq / latest - 1) * 100;
      if (liq && side === 'long') liqGap = (1 - liq / latest) * 100;
      const state = liq ? (liqGap < 1.2 ? '危险' : liqGap < 3 ? '偏紧' : '正常') : '未提供强平价';
      const pnlEl = document.getElementById('positionPnl');
      if (pnlEl) {{
        pnlEl.textContent = `${{pnl >= 0 ? '+' : ''}}${{pnl.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }})}} (${{fmtPct(roi)}})`;
        pnlEl.classList.toggle('loss', pnl < 0);
      }}
      setText('positionMarkPrice', fmtPrice(latest));
      setText('positionMmr', `${{marginRatio.toFixed(2)}}%`);
      const liqState = document.getElementById('positionLiqState');
      if (liqState) {{
        liqState.textContent = `强平状态：${{state}} · 距离强平约 ${{liq ? liqGap.toFixed(2) : '-'}}% · 维持保证金率为估算值，实际以 OKX 账户页为准`;
        liqState.classList.toggle('danger', state === '危险');
        liqState.classList.toggle('warn', state === '偏紧');
      }}
    }}
    let liveSupport = {indicators.support};
    let liveResistance = {indicators.resistance};
    let liveRefreshInFlight = false;
    let websocketHasLivePrice = false;
    function updateSimplePlan(latest, support, resistance, source) {{
      const entry = Number(positionConfig.activeEntry || positionConfig.shortEntry || 0);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const midRange = (support + resistance) / 2;
      const shortTp1 = Math.min(entry || latest * 0.996, latest * 0.992, midRange);
      const shortTp2 = Math.min(support, shortTp1 * 0.992);
      const shortTp3 = Math.min(support * 0.985, shortTp2 * 0.99);
      const stopCandidates = [resistance * 1.002, latest * 1.008];
      if (entry > 0) stopCandidates.push(entry * 1.026);
      if (liq > 0) stopCandidates.push(liq * 0.985);
      const shortStop = Math.min(...stopCandidates.filter(v => Number.isFinite(v) && v > latest));
      const shortEntry1 = Math.max(resistance * 0.996, latest * 1.002);
      const shortEntry2 = Math.max(resistance * 1.002, shortEntry1 * 1.004);
      const shortBreakdown = Math.min(support * 0.998, latest * 0.996);
      const longEntry1 = Math.min(support * 1.001, latest * 0.995);
      const longEntry2 = Math.min(support * 0.985, longEntry1 * 0.99);
      const liqGap = liq ? (liq / latest - 1) * 100 : NaN;
      setText('simpleCurrentPoint', fmtPrice(latest));
      setText('simpleTakeProfit', `${{fmtPrice(shortTp1)}} / ${{fmtPrice(shortTp2)}} / ${{fmtPrice(shortTp3)}} 分批止盈，第一档先减30%-40%`);
      setText('simpleStopLoss', `${{fmtPrice(shortStop)}} 硬止损；若15分钟收盘站上 ${{fmtPrice(resistance)}}，先减仓或离场`);
      setText('simpleShortEntry', `反弹 ${{fmtPrice(shortEntry1)}} - ${{fmtPrice(shortEntry2)}} 受阻再加空；跌破 ${{fmtPrice(shortBreakdown)}} 后回抽不破可追空`);
      setText('simpleLongEntry', `仅在 ${{fmtPrice(longEntry1)}} - ${{fmtPrice(longEntry2)}} 企稳，或15分钟重新站上 ${{fmtPrice(resistance)}} 后回踩不破再开多`);
      setText('simplePlanContext', `支撑 ${{fmtPrice(support)}} · 阻力 ${{fmtPrice(resistance)}} · 开仓均价 ${{fmtPrice(entry)}} · 强平 ${{fmtPrice(liq)}} · 距强平 ${{Number.isFinite(liqGap) ? liqGap.toFixed(2) + '%' : '-'}} · 数据源：${{source}}`);
      setText('liveHeaderMeta', `本次刷新：${{fmtTime(new Date())}} 北京时间 · 标的：BTCUSDT · 数据源：${{source}}`);
      updatePositionUi(latest);
    }}
    const okxHosts = ['https://openapi.okx.com', 'https://www.okx.com'];
    const okxUrl = (host, path) => `${{host}}${{path}}${{path.includes('?') ? '&' : '?'}}_=${{Date.now()}}`;
    const withCacheBust = url => `${{url}}${{url.includes('?') ? '&' : '?'}}_=${{Date.now()}}`;
    async function fetchJson(label, path) {{
      const errors = [];
      for (const host of okxHosts) {{
        try {{
          const response = await fetch(okxUrl(host, path), {{ cache: 'no-store' }});
          if (!response.ok) throw new Error(`${{host}} HTTP ${{response.status}}`);
          const payload = await response.json();
          if (payload.code && payload.code !== '0') throw new Error(`${{host}} code ${{payload.code}}: ${{payload.msg || ''}}`);
          return payload;
        }} catch (error) {{
          errors.push(`${{host}}: ${{String(error)}}`);
        }}
      }}
      throw new Error(`${{label}} all OKX hosts failed: ${{errors.join(' | ')}}`);
    }}
    async function fetchAbsoluteJson(label, urls) {{
      const errors = [];
      for (const url of urls) {{
        try {{
          const response = await fetch(withCacheBust(url), {{ cache: 'no-store' }});
          if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
          return await response.json();
        }} catch (error) {{
          errors.push(`${{url}}: ${{String(error)}}`);
        }}
      }}
      throw new Error(`${{label}} failed: ${{errors.join(' | ')}}`);
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
    function parseForwardCandles(rows) {{
      return rows.map(row => ({{ high:Number(row[2]), low:Number(row[3]), close:Number(row[4]), quoteVolume:Number(row[7] || row[5] || 0) }}));
    }}
    function parseReverseCandles(rows) {{
      return rows.slice().reverse().map(row => ({{ high:Number(row[2]), low:Number(row[3]), close:Number(row[4]), quoteVolume:Number(row[6] || row[5] || 0) }}));
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
    function applyLiveSnapshot(snapshot, reason) {{
      const c15 = snapshot.c15;
      const c1h = snapshot.c1h;
      const c4h = snapshot.c4h;
      const latest = snapshot.latest;
      const latestCandle = lastItem(c15);
      const support = Math.min(...c15.slice(-24).map(c => c.low));
      const resistance = Math.max(...c15.slice(-24).map(c => c.high));
      liveSupport = support;
      liveResistance = resistance;
      const returns = c15.slice(1).map((c, i) => pct(c.close, c15[i].close));
      const avg = returns.reduce((a, b) => a + b, 0) / Math.max(returns.length, 1);
      const vol = Math.sqrt(returns.reduce((a, b) => a + (b - avg) ** 2, 0) / Math.max(returns.length, 1));
      const volumeSlice = c15.slice(-33, -1);
      const volumeBase = volumeSlice.reduce((a, c) => a + c.quoteVolume, 0) / Math.max(volumeSlice.length, 1);
      const volumeRatio = volumeBase && latestCandle ? latestCandle.quoteVolume / volumeBase : 1;
      setText('liveLatestPrice', fmtPrice(latest));
      setText('liveChange15m', fmtPct(pct(latest, c15.length >= 2 ? c15[c15.length - 2].close : latest)));
      setText('liveChange1h', fmtPct(pct(latest, c1h.length >= 2 ? c1h[c1h.length - 2].close : latest)));
      setText('liveChange4h', fmtPct(pct(latest, c4h.length >= 2 ? c4h[c4h.length - 2].close : latest)));
      setText('liveFunding', fmtPct(snapshot.funding));
      setText('liveOpenInterest', fmtPrice(snapshot.openInterest));
      setText('liveStructure', `短线支撑：${{fmtPrice(support)}} · 短线阻力：${{fmtPrice(resistance)}} · 15分钟波动：${{fmtPct(vol)}} · 成交量倍率：${{volumeRatio.toFixed(2)}}x · 数据：${{snapshot.source}}`);
      updateSimplePlan(latest, support, resistance, snapshot.source);
      setText('liveFetchMeta', `实时抓取状态：成功 · ${{snapshot.source}} · 标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}} · 模式：${{reason}}`);
      const status = document.getElementById('liveStatus');
      if (status) status.innerHTML = `<li>本次已现场获取行情；数据源：${{snapshot.source}}；触发方式：${{reason}}；手机端会在OKX失败后自动尝试Binance和Bybit。</li>`;
    }}
    async function fetchBinanceSnapshot() {{
      const [premium, c15Raw, c1hRaw, c4hRaw, oiRaw] = await Promise.all([
        fetchAbsoluteJson('Binance mark price', ['https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT']),
        fetchAbsoluteJson('Binance 15m candles', ['https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=96']),
        fetchAbsoluteJson('Binance 1h candles', ['https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=24']),
        fetchAbsoluteJson('Binance 4h candles', ['https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=4h&limit=8']),
        fetchAbsoluteJson('Binance open interest', ['https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT'])
      ]);
      return {{
        source: '币安U本位永续REST备用',
        latest: Number(premium.markPrice || premium.indexPrice || 0),
        funding: Number(premium.lastFundingRate || 0) * 100,
        openInterest: Number(oiRaw.openInterest || NaN),
        c15: parseForwardCandles(c15Raw || []),
        c1h: parseForwardCandles(c1hRaw || []),
        c4h: parseForwardCandles(c4hRaw || [])
      }};
    }}
    async function fetchBybitSnapshot() {{
      const [ticker, c15Raw, c1hRaw, c4hRaw] = await Promise.all([
        fetchAbsoluteJson('Bybit ticker', ['https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT']),
        fetchAbsoluteJson('Bybit 15m candles', ['https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15&limit=96']),
        fetchAbsoluteJson('Bybit 1h candles', ['https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=60&limit=24']),
        fetchAbsoluteJson('Bybit 4h candles', ['https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=240&limit=8'])
      ]);
      const row = ticker.result && ticker.result.list && ticker.result.list.length ? ticker.result.list[0] : {{}};
      return {{
        source: 'Bybit U本位永续REST备用',
        latest: Number(row.markPrice || row.lastPrice || 0),
        funding: Number(row.fundingRate || 0) * 100,
        openInterest: Number(row.openInterest || NaN),
        c15: parseReverseCandles((c15Raw.result && c15Raw.result.list) || []),
        c1h: parseReverseCandles((c1hRaw.result && c1hRaw.result.list) || []),
        c4h: parseReverseCandles((c4hRaw.result && c4hRaw.result.list) || [])
      }};
    }}
    async function refreshFallbackMarket(reason, originalError) {{
      const errors = [`OKX失败：${{String(originalError)}}`];
      for (const loader of [fetchBinanceSnapshot, fetchBybitSnapshot]) {{
        try {{
          const snapshot = await loader();
          if (!snapshot.latest || !snapshot.c15.length || !snapshot.c1h.length || !snapshot.c4h.length) throw new Error('备用源数据不完整');
          applyLiveSnapshot(snapshot, reason);
          return;
        }} catch (error) {{
          errors.push(String(error));
        }}
      }}
      throw new Error(errors.join(' | '));
    }}
    async function refreshLiveMarket(reason = 'page-load') {{
      if (liveRefreshInFlight) return;
      liveRefreshInFlight = true;
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
        liveSupport = support;
        liveResistance = resistance;
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
        updateSimplePlan(latest, support, resistance, 'OKX REST现场抓取');
        const softWarnings = [fundingResult, oiResult].filter(item => !item.ok).map(item => `${{item.label}}失败：${{item.error}}`);
        setText('liveFetchMeta', `实时抓取状态：成功 · OKX标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}} · 模式：${{reason}}${{softWarnings.length ? ' · 部分数据缺失：' + softWarnings.join('；') : ''}}`);
        const status = document.getElementById('liveStatus');
        if (status) status.innerHTML = `<li>本次已现场获取 OKX 行情；触发方式：${{reason}}；WebSocket失败时会每15秒REST轮询。</li>${{softWarnings.map(item => `<li>${{item}}</li>`).join('')}}`;
      }} catch (error) {{
        try {{
          setText('liveFetchMeta', `实时抓取状态：OKX失败，正在尝试Binance/Bybit备用源 · ${{fmtTime(new Date())}}`);
          await refreshFallbackMarket(`${{reason}}-multi-source`, error);
        }} catch (fallbackError) {{
          setText('liveFetchMeta', `实时抓取状态：失败 · ${{String(fallbackError)}} · ${{fmtTime(new Date())}}`);
          const status = document.getElementById('liveStatus');
          if (status) status.innerHTML = `<li>浏览器实时行情刷新失败：${{String(fallbackError)}}</li>`;
        }}
      }} finally {{
        liveRefreshInFlight = false;
      }}
    }}
    function startOkxWebSocket() {{
      try {{
        const ws = new WebSocket('wss://ws.okx.com:8443/ws/v5/public');
        ws.onopen = () => {{
          setText('liveFetchMeta', `实时抓取状态：WebSocket连接中 · ${{fmtTime(new Date())}}`);
          ws.send(JSON.stringify({{
            op: 'subscribe',
            args: [
              {{ channel: 'mark-price', instId: 'BTC-USDT-SWAP' }},
              {{ channel: 'candle15m', instId: 'BTC-USDT-SWAP' }}
            ]
          }}));
        }};
        ws.onmessage = event => {{
          try {{
            const message = JSON.parse(event.data);
            if (!message.data || !message.data.length) return;
            const arg = message.arg || {{}};
            const row = message.data[0];
            if (arg.channel === 'mark-price') {{
              const latest = Number(row.markPx || 0);
              if (latest > 0) {{
                websocketHasLivePrice = true;
                setText('liveLatestPrice', fmtPrice(latest));
                updateSimplePlan(latest, liveSupport, liveResistance, 'OKX WebSocket实时推送');
                setText('liveFetchMeta', `实时抓取状态：WebSocket成功 · OKX标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}}`);
              }}
            }}
            if (arg.channel === 'candle15m' && Array.isArray(row)) {{
              const high = Number(row[2]);
              const low = Number(row[3]);
              const close = Number(row[4]);
              if (Number.isFinite(high) && Number.isFinite(low)) {{
                liveSupport = Math.min(liveSupport, low);
                liveResistance = Math.max(liveResistance, high);
                setText('liveStructure', `短线支撑：${{fmtPrice(liveSupport)}} · 短线阻力：${{fmtPrice(liveResistance)}} · 数据：OKX WebSocket实时推送`);
                if (close > 0) updateSimplePlan(close, liveSupport, liveResistance, 'OKX WebSocket实时推送');
              }}
            }}
          }} catch (error) {{
            setText('liveFetchMeta', `实时抓取状态：WebSocket消息解析失败 · ${{String(error)}}`);
          }}
        }};
        ws.onerror = () => {{
          websocketHasLivePrice = false;
          setText('liveFetchMeta', `实时抓取状态：WebSocket失败，切换为15秒REST轮询 · ${{fmtTime(new Date())}}`);
          refreshLiveMarket('websocket-error-rest-fallback');
        }};
        ws.onclose = () => {{
          websocketHasLivePrice = false;
          setTimeout(startOkxWebSocket, 5000);
        }};
      }} catch (error) {{
        setText('liveFetchMeta', `实时抓取状态：WebSocket启动失败 · ${{String(error)}}`);
      }}
    }}
    refreshLiveMarket('page-load');
    startOkxWebSocket();
    setInterval(() => {{
      if (document.visibilityState !== 'hidden' && !websocketHasLivePrice) refreshLiveMarket('REST-15s-fallback');
    }}, 15000);
    setInterval(() => {{
      if (document.visibilityState !== 'hidden' && websocketHasLivePrice) refreshLiveMarket('REST-60s-sync');
    }}, 60000);
    document.addEventListener('visibilitychange', () => {{ if (document.visibilityState === 'visible') refreshLiveMarket('page-visible'); }});
    window.addEventListener('focus', () => refreshLiveMarket('window-focus'));
  </script>
</body>
</html>
"""
