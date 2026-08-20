from __future__ import annotations

import html
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .advice import Advice
from .binance import MarketData
from .config import PositionConfig, PreferenceConfig
from .indicators import Indicators
from .macro_events import MacroBrief


CN_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ACCOUNT_WORKER_URL = "https://btc-account.kangli0327-btc.workers.dev"


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


def sprint_stage(equity_usdt: float) -> dict[str, float | str]:
    equity_cny = equity_usdt * 7.2
    stages: list[dict[str, float | str]] = [
        {"name": "阶段1：5000 -> 10000元", "min": 0.0, "max": 10000.0, "risk": 0.035, "weekly": 0.40},
        {"name": "阶段2：10000 -> 30000元", "min": 10000.0, "max": 30000.0, "risk": 0.030, "weekly": 0.30},
        {"name": "阶段3：30000 -> 100000元", "min": 30000.0, "max": 100000.0, "risk": 0.020, "weekly": 0.20},
        {"name": "阶段4：100000 -> 300000元", "min": 100000.0, "max": 300000.0, "risk": 0.015, "weekly": 0.12},
    ]
    for stage in stages:
        if equity_cny < float(stage["max"]):
            return stage
    return stages[-1]


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
    sprint = sprint_stage(position.account_equity_usdt)
    single_risk_usdt = position.account_equity_usdt * float(sprint["risk"])
    equity_cny = position.account_equity_usdt * 7.2
    weekly_risk_cny = equity_cny * float(sprint["weekly"])
    weekly_profit_cny = 0.0
    target_progress = min(equity_cny / 300000 * 100, 100)
    macro_high_soon = any(
        event.impact in {"高", "中高"} and 0 <= (event.scheduled_at.astimezone(CN_TZ) - generated_at).total_seconds() <= 30 * 60
        for event in macro_brief.events
    )
    if liq_state == "危险":
        sprint_status = "禁止开新仓"
        sprint_reason = "强平距离过近，先减仓或设置硬止损。"
    elif macro_high_soon:
        sprint_status = "只管理持仓"
        sprint_reason = "距离高影响宏观数据不足30分钟，暂停开新仓。"
    elif indicators.risk_level == "高":
        sprint_status = "轻仓交易"
        sprint_reason = "波动风险偏高，只允许小仓位按计划执行。"
    elif active_side != "flat":
        sprint_status = "持仓优先"
        sprint_reason = "已有合约仓位，先执行止盈止损，再考虑新增方向。"
    else:
        sprint_status = "可等待触发"
        sprint_reason = "无持仓时只在关键支撑阻力触发，不追中间价。"

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
            "sprintSingleRisk": single_risk_usdt,
            "sprintWeeklyRiskCny": weekly_risk_cny,
            "sprintWeeklyProfitCny": weekly_profit_cny,
            "sprintWeeklyLossCny": max(0.0, -weekly_profit_cny),
            "fallbackCnyRate": 7.2,
        },
        ensure_ascii=False,
    )
    strategy_basis_html = "".join(
        f"<div class=\"reason-card\"><div class=\"reason-title\">{html.escape(title)}</div><p>{html.escape(body)}</p></div>"
        for title, body in (advice.strategy_cards or [])
    )
    strategy_json = json.dumps(
        {
            "longScore": advice.long_score,
            "shortScore": advice.short_score,
            "riskScore": advice.risk_score,
            "tradeMode": advice.trade_mode,
            "strategyReason": advice.strategy_reason,
            "rsi15m": indicators.rsi_15m,
            "rsi1h": indicators.rsi_1h,
            "rsi4h": indicators.rsi_4h,
            "macdHist15m": indicators.macd_hist_15m,
            "macdHist1h": indicators.macd_hist_1h,
            "macdHist4h": indicators.macd_hist_4h,
            "volumeRatio15m": indicators.volume_ratio_15m,
            "volumeRatio1h": indicators.volume_ratio_1h,
            "volumeRatio4h": indicators.volume_ratio_4h,
            "emaState15m": indicators.ema_state_15m,
            "emaState1h": indicators.ema_state_1h,
            "emaState4h": indicators.ema_state_4h,
            "atr15m": indicators.atr_15m,
            "atr15mPct": indicators.atr_15m_pct,
            "vwap24h": indicators.vwap_24h,
            "priceVsVwapPct": indicators.price_vs_vwap_pct,
            "support": indicators.support,
            "resistance": indicators.resistance,
            "fundingRatePct": indicators.funding_rate_pct,
            "positionContext": indicators.position_context,
        },
        ensure_ascii=False,
    )
    points = chart_points(market)
    generated_text = fmt_dt(generated_at)
    account_worker_url = os.environ.get("ACCOUNT_WORKER_URL", "").strip() or DEFAULT_ACCOUNT_WORKER_URL

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
    .sprint {{ background:#0f172a; color:#f8fafc; border-color:#1e293b; }}
    .sprint h2 {{ color:#fff; }}
    .sprint-top {{ display:grid; grid-template-columns:1.2fr .8fr; gap:14px; align-items:start; }}
    .sprint-status {{ font-size:28px; line-height:1.08; font-weight:820; margin:0 0 8px; }}
    .sprint-reason {{ color:#cbd5e1; margin:0; }}
    .sprint-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-top:14px; }}
    .sprint-item {{ background:#111827; border:1px solid #334155; border-radius:8px; padding:10px; }}
    .sprint-item .label {{ color:#94a3b8; }}
    .sprint-item .value {{ color:#fff; font-size:20px; }}
    .sprint-item.stage .value {{ white-space:normal; word-break:keep-all; overflow-wrap:normal; font-size:18px; line-height:1.25; }}
    .equity-main {{ font-size:24px; font-weight:820; }}
    .equity-sub {{ color:#cbd5e1; font-size:13px; margin-top:2px; }}
    .progress {{ width:100%; height:9px; background:#1e293b; border-radius:999px; overflow:hidden; margin-top:10px; }}
    .progress span {{ display:block; height:100%; background:#22c55e; border-radius:999px; }}
    .sprint-warning {{ color:#fde68a; font-size:13px; margin-top:10px; }}
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
    .pnl-label {{ color:#8a8f98; font-size:14px; text-decoration:underline dashed #858b94 1px; text-underline-offset:4px; white-space:nowrap; }}
    .pnl-value {{ margin-top:8px; font-size:21px; line-height:1.1; font-weight:780; color:#2e7d32; white-space:nowrap; }}
    .pnl-value.loss {{ color:#b42318; }}
    .position-grid {{ display:grid; grid-template-columns:repeat(3,1fr); column-gap:28px; row-gap:28px; }}
    .okx-label {{ color:#8a8f98; font-size:14px; line-height:1.15; text-decoration:underline dashed #858b94 1px; text-underline-offset:4px; }}
    .okx-value {{ margin-top:9px; font-size:21px; line-height:1.1; font-weight:650; color:#101318; overflow-wrap:anywhere; }}
    .margin-inline {{ display:inline-flex; align-items:center; gap:8px; }}
    .plus-dot {{ display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border:2px solid #111; border-radius:50%; font-size:20px; line-height:20px; font-weight:800; }}
    .liq-note {{ margin-top:18px; padding:10px 12px; border-radius:8px; background:#f8fafc; color:#475467; font-size:14px; }}
    .liq-note.danger {{ background:#fee4e2; color:#b42318; }}
    .liq-note.warn {{ background:#fef0c7; color:#b45309; }}
    ul {{ padding-left:20px; margin:8px 0 0; }} li {{ margin:6px 0; }}
    canvas {{ width:100%; height:260px; display:block; }}
    .small {{ color:var(--muted); font-size:13px; }}
    .plan {{ border-left:4px solid #475467; }}
    .market-price {{ text-align:center; padding:18px 14px 20px; }}
    .market-price .label {{ font-size:14px; }}
    .market-price .value {{ font-size:clamp(38px,12vw,72px); line-height:1; letter-spacing:0; }}
    .plan-lines {{ display:grid; gap:8px; margin-top:10px; }}
    .plan-line {{ display:grid; grid-template-columns:92px 1fr; gap:10px; align-items:start; padding:10px 0; border-top:1px solid var(--line); }}
    .plan-line:first-child {{ border-top:0; }}
    .plan-label {{ color:#475467; font-weight:760; }}
    .reason-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:10px; margin-top:12px; }}
    .reason-card {{ background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }}
    .reason-title {{ font-weight:780; margin-bottom:6px; color:#102a43; }}
    .reason-card p {{ margin:0; color:#344054; }}
    footer {{ padding:18px 14px 30px; color:var(--muted); text-align:center; font-size:13px; }}
    @media (max-width:720px) {{ main {{ padding:10px; }} .grid {{ gap:10px; }} .span-4,.span-6 {{ grid-column:span 12; }} section,.tile {{ padding:12px; }} .headline {{ font-size:20px; }} canvas {{ height:220px; }} .sprint-top {{ grid-template-columns:1fr; }} .sprint-status {{ font-size:25px; }} .sprint-grid {{ grid-template-columns:repeat(2,1fr); }} .reason-grid {{ grid-template-columns:1fr; }} .position-card {{ padding:14px; }} .position-head {{ gap:8px; margin-bottom:20px; }} .contract-title {{ font-size:25px; }} .okx-badge {{ font-size:18px; min-height:30px; padding:3px 9px; }} .pnl-box {{ min-width:136px; }} .pnl-label,.okx-label {{ font-size:13px; }} .pnl-value,.okx-value {{ font-size:19px; }} .position-grid {{ column-gap:14px; row-gap:22px; }} }}
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
    <section class="sprint">
      <h2>冲刺账户模式</h2>
      <div class="sprint-top">
        <div>
          <div class="sprint-status" id="sprintStatus">{html.escape(sprint_status)}</div>
          <p class="sprint-reason" id="sprintReason">{html.escape(sprint_reason)}</p>
          <div class="progress" aria-label="冲刺目标进度"><span id="sprintProgressBar" style="width:{target_progress:.2f}%"></span></div>
          <div class="sprint-warning" id="sprintStageBasis">目标：5000元 -> 300000元；当前进度按 1 USDT≈7.2元估算，不作为汇率承诺。</div>
        </div>
        <div>
          <div class="sprint-item">
            <div class="label">今天只看这一句</div>
            <div class="value" id="sprintOneLine">{html.escape(sprint_status)}：{html.escape(sprint_reason)}</div>
          </div>
        </div>
      </div>
      <div class="sprint-grid">
        <div class="sprint-item stage"><div class="label">当前阶段</div><div class="value" id="sprintStageName">{html.escape(str(sprint["name"]))}</div></div>
        <div class="sprint-item"><div class="label">账户权益人民币</div><div class="value"><div class="equity-main" id="sprintEquityCny">¥{fmt_price(equity_cny)}</div><div class="equity-sub" id="sprintEquity">{fmt_price(position.account_equity_usdt)} USDT</div></div></div>
        <div class="sprint-item"><div class="label">一周收益 / 最大亏损</div><div class="value" id="sprintWeeklyRisk">¥{fmt_price(weekly_profit_cny)} / ¥{fmt_price(weekly_risk_cny)}</div></div>
        <div class="sprint-item"><div class="label">用户设定杠杆</div><div class="value" id="sprintLeverage">100x</div></div>
        <div class="sprint-item"><div class="label">本周风控状态</div><div class="value" id="weeklyRiskStatus">亏损触线停手</div></div>
        <div class="sprint-item"><div class="label">权益刷新</div><div class="value" id="accountRefreshState">等待实时账户接口</div></div>
      </div>
    </section>

    <section>
      <h2>市场快照</h2>
      <div class="market-price">
        <div class="label">BTCUSDT 最新标记价格</div>
        <div class="value" id="liveLatestPrice">{fmt_price(indicators.latest_price)}</div>
        <div class="small" id="livePriceSource">浏览器打开后现场刷新</div>
      </div>
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
      <p><strong>策略模式：</strong><span id="strategyTradeMode">{html.escape(advice.trade_mode)}</span> · 多头确认分 <span id="strategyLongScore">{advice.long_score}</span> / 空头确认分 <span id="strategyShortScore">{advice.short_score}</span> / 风险评分 <span id="strategyRiskScore">{advice.risk_score}</span></p>
      <p><strong>提前预警：</strong>多头 <span id="earlyLongWarning">-</span> / 空头 <span id="earlyShortWarning">-</span> · <span id="earlyWarningMode">等待1m/5m数据</span></p>
      <div class="plan-lines">
        <div class="plan-line"><div class="plan-label">当前点位</div><div id="simpleCurrentPoint">{fmt_price(indicators.latest_price)}</div></div>
        <div class="plan-line"><div class="plan-label">止盈点位</div><div id="simpleTakeProfit">{fmt_price(indicators.latest_price * 0.988)} / {fmt_price(indicators.support)} / {fmt_price(indicators.support * 0.965)} 分批止盈</div></div>
        <div class="plan-line"><div class="plan-label">止损点位</div><div id="simpleStopLoss">{fmt_price(indicators.resistance * 1.002)} 附近硬止损，接近强平前必须离场</div></div>
        <div class="plan-line"><div class="plan-label">加空计划</div><div id="simpleShortEntry">{fmt_price(indicators.resistance * 0.998)} - {fmt_price(indicators.resistance * 1.002)} 反弹受阻再考虑</div></div>
        <div class="plan-line"><div class="plan-label">开多计划</div><div id="simpleLongEntry">{fmt_price(indicators.support)} - {fmt_price(indicators.support * 0.985)} 企稳后分批开多</div></div>
        <div class="plan-line"><div class="plan-label">保证金</div><div id="simpleMarginBudget">本次最大保证金：{fmt_price(single_risk_usdt * 6)} USDT，必须和止损距离一起收缩</div></div>
        <div class="plan-line"><div class="plan-label">触发状态</div><div id="simpleTriggerStatus">等待浏览器实时行情刷新</div></div>
      </div>
      <p class="small" id="simplePlanContext">支撑 {fmt_price(indicators.support)} · 阻力 {fmt_price(indicators.resistance)} · ATR {fmt_price(indicators.atr_15m)} · VWAP {fmt_price(indicators.vwap_24h)} · 数据源：模板生成</p>
    </section>

    <section>
      <h2>策略依据</h2>
      <p><strong>核心判断：</strong><span id="strategyReason">{html.escape(advice.strategy_reason or "等待多周期指标确认。")}</span></p>
      <div class="reason-grid" id="strategyCards">{strategy_basis_html}</div>
      <p class="small">点位只在策略评分和入场条件成立后执行；不是单纯用支撑阻力套公式。</p>
    </section>

    <section id="macroSection">
      <h2>未来24小时宏观事件</h2>
      <p id="macroSummary">{html.escape(macro_brief.summary)}</p>
      <p><strong>BTC波动预测：</strong><span id="macroForecast">{html.escape(macro_brief.forecast)}</span></p>
      <p class="small" id="macroWindow">窗口：{macro_brief.window_start:%Y-%m-%d %H:%M} - {macro_brief.window_end:%Y-%m-%d %H:%M} 北京时间</p>
      <p class="small" id="macroWarnings"></p>
      <ul id="macroEventsList">{macro_events_html}</ul>
      <h3>最近7天关键消息</h3>
      <ul id="recentMacroEventsList"></ul>
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
    const strategyConfig = {strategy_json};
    const accountWorkerUrl = {json.dumps(account_worker_url, ensure_ascii=False)} || window.BTC_ACCOUNT_WORKER_URL || localStorage.getItem('BTC_ACCOUNT_WORKER_URL') || '';
    const canvas = document.getElementById('priceChart');
    const ctx = canvas ? canvas.getContext('2d') : null;
    function drawChart() {{
      if (!canvas || !ctx) return;
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
    const fmtMoney2 = value => Number.isFinite(value) ? value.toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }}) : '-';
    const fmtCny = value => Number.isFinite(value) ? `¥${{value.toLocaleString('zh-CN', {{ minimumFractionDigits: 0, maximumFractionDigits: 0 }})}}` : '-';
    const fmtPct = value => Number.isFinite(value) ? `${{value >= 0 ? '+' : ''}}${{value.toFixed(2)}}%` : '-';
    const fmtTime = value => {{
      const pad = number => String(number).padStart(2, '0');
      return `${{value.getFullYear()}}-${{pad(value.getMonth() + 1)}}-${{pad(value.getDate())}} ${{pad(value.getHours())}}:${{pad(value.getMinutes())}}:${{pad(value.getSeconds())}}`;
    }};
    const pct = (a, b) => b ? (a / b - 1) * 100 : 0;
    const setText = (id, text) => {{ const el = document.getElementById(id); if (el) el.textContent = text; }};
    let lastAccountRefreshAt = 0;
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
      updateSprintUi(latest, liqGap, state);
    }}
    function sprintStageForCny(equityCny) {{
      const equity = Number(equityCny || 0);
      if (equity < 10000) return {{ name: '阶段1：5000 -> 10000元', min: 5000, max: 10000, weeklyPct: 0.40 }};
      if (equity < 30000) return {{ name: '阶段2：10000 -> 30000元', min: 10000, max: 30000, weeklyPct: 0.30 }};
      if (equity < 100000) return {{ name: '阶段3：30000 -> 100000元', min: 30000, max: 100000, weeklyPct: 0.20 }};
      return {{ name: '阶段4：100000 -> 300000元', min: 100000, max: 300000, weeklyPct: 0.12 }};
    }}
    function applySprintStageFromEquity(equityCny, equityUsdt, rate, serverLimitCny) {{
      const stage = sprintStageForCny(equityCny);
      const displayLimit = Number.isFinite(Number(serverLimitCny)) && Number(serverLimitCny) > 0
        ? Number(serverLimitCny)
        : Number(equityCny || 0) * stage.weeklyPct;
      const progress = Math.max(0, Math.min(100, Number(equityCny || 0) / 300000 * 100));
      setText('sprintStageName', stage.name);
      setText('sprintStageBasis', `目标：5000元 -> 300000元；当前按实时账户权益 ${{fmtCny(equityCny)}} 计算阶段。OKX接口权益 ${{fmtMoney2(equityUsdt)}} USDT × 汇率 ${{Number(rate || 0).toFixed(3)}} = 页面换算权益 ${{fmtCny(equityCny)}}。`);
      const bar = document.getElementById('sprintProgressBar');
      if (bar) bar.style.width = `${{progress.toFixed(2)}}%`;
      positionConfig.sprintWeeklyRiskCny = displayLimit;
      return {{ stage, weeklyLossLimitCny: displayLimit }};
    }}
    function applyAccountSnapshot(account) {{
      if (!account || !account.ok) return;
      const syncedAt = account.okxFetchedAt || account.workerFetchedAt || account.updatedAt || new Date().toISOString();
      const rate = Number(account.cnyRate || positionConfig.fallbackCnyRate || 7.2);
      const equityUsdt = Number(account.equityUsdt || positionConfig.accountEquity || 0);
      const equityCny = Number(account.equityCny || equityUsdt * rate);
      const weekLossCny = Number(account.weekLossCny || 0);
      const weekRiskCny = Number(account.weekRiskCny || positionConfig.sprintWeeklyRiskCny || 0);
      positionConfig.accountEquity = equityUsdt;
      applySprintStageFromEquity(equityCny, equityUsdt, rate, weekRiskCny);
      setText('sprintEquityCny', fmtCny(equityCny));
      setText('sprintEquity', `${{fmtMoney2(equityUsdt)}} USDT · 汇率 ${{rate.toFixed(3)}}`);
      setText('sprintWeeklyRisk', `${{fmtCny(weekLossCny)}} / ${{fmtCny(weekRiskCny)}}`);
      const hedgeText = account.hasHedgedPositions ? ' · 检测到双向持仓，显示主仓位' : '';
      setText('accountRefreshState', `成功 · ${{fmtTime(new Date(syncedAt))}}${{hedgeText}}`);
      if (account.position) {{
        const p = account.position;
        const side = p.side || positionConfig.activeSide;
        positionConfig.activeSide = side;
        positionConfig.activeQty = Number(p.quantityBtc || positionConfig.activeQty || 0);
        positionConfig.activeEntry = Number(p.entryPrice || positionConfig.activeEntry || 0);
        positionConfig.activeLeverage = Number(p.leverage || 100);
        positionConfig.initialMargin = Number(p.marginUsdt || positionConfig.initialMargin || 0);
        positionConfig.liquidationPrice = Number(p.liquidationPrice || positionConfig.liquidationPrice || 0);
        setText('positionSideBadge', side === 'short' ? '空' : side === 'long' ? '多' : '无仓');
        setText('positionLeverage', `${{positionConfig.activeLeverage || 100}}x`);
        setText('positionQty', `${{positionConfig.activeQty || 0}}`);
        setText('positionEntry', fmtPrice(positionConfig.activeEntry));
        setText('positionMargin', fmtPrice(positionConfig.initialMargin));
        setText('positionLiqPrice', fmtPrice(positionConfig.liquidationPrice));
      }} else {{
        positionConfig.activeSide = 'flat';
        positionConfig.activeQty = 0;
        positionConfig.activeEntry = 0;
        positionConfig.initialMargin = 0;
        positionConfig.liquidationPrice = 0;
        setText('positionSideBadge', '无仓');
        setText('positionLeverage', '100x');
        setText('positionQty', '0');
        setText('positionEntry', '-');
        setText('positionMargin', '-');
        setText('positionLiqPrice', '-');
      }}
      updateSimplePlan(liveLatest, liveSupport, liveResistance, 'OKX账户实时同步');
    }}
    async function refreshAccount(reason = 'page-load') {{
      if (!accountWorkerUrl) {{
        setText('accountRefreshState', '实时账户接口未配置，持仓不会同步');
        setText('sprintEquityCny', fmtCny(Number(positionConfig.accountEquity || 0) * Number(positionConfig.fallbackCnyRate || 7.2)));
        setText('sprintWeeklyRisk', `${{fmtCny(positionConfig.sprintWeeklyLossCny || 0)}} / ${{fmtCny(positionConfig.sprintWeeklyRiskCny || 0)}}`);
        return;
      }}
      lastAccountRefreshAt = Date.now();
      try {{
        setText('accountRefreshState', `刷新中 · ${{fmtTime(new Date())}}`);
        const response = await fetch(withCacheBust(accountWorkerUrl), {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const payload = await response.json();
        if (!payload.ok) throw new Error(payload.error || 'Worker返回失败');
        applyAccountSnapshot(payload);
      }} catch (error) {{
        setText('accountRefreshState', `失败 · ${{String(error).slice(0, 42)}}`);
      }}
    }}
    function refreshAccountSoon(reason) {{
      if (!accountWorkerUrl) return;
      if (Date.now() - lastAccountRefreshAt < 10000) return;
      refreshAccount(reason);
    }}
    function updateSprintUi(latest, liqGap, liqState) {{
      const hasPosition = positionConfig.activeSide !== 'flat' && Number(positionConfig.activeQty || 0) > 0;
      let status = '可等待触发';
      let reason = '无持仓时只在关键支撑阻力触发，不追中间价。';
      if (liqState === '危险') {{
        status = '禁止开新仓';
        reason = '强平距离过近，先减仓或设置硬止损。';
      }} else if (liqState === '偏紧') {{
        status = '只减不加';
        reason = '强平距离偏紧，禁止加仓，优先保护保证金。';
      }} else if (hasPosition) {{
        status = '持仓优先';
        reason = '已有合约仓位，先执行止盈止损，再考虑新增方向。';
      }}
      setText('sprintStatus', status);
      setText('sprintReason', reason);
      setText('sprintOneLine', `${{status}}：${{reason}}`);
      setText('sprintEquity', `${{fmtMoney2(positionConfig.accountEquity)}} USDT`);
    }}
    let liveSupport = {indicators.support};
    let liveResistance = {indicators.resistance};
    let liveLatest = {indicators.latest_price};
    let lockedPositionPlan = null;
    let lockedPositionPlanKey = '';
    let liveRefreshInFlight = false;
    let websocketHasLivePrice = false;
    function validPrice(value, fallback) {{
      return Number.isFinite(value) && value > 0 ? value : fallback;
    }}
    function calcLiqGap(side, latest) {{
      const liq = Number(positionConfig.liquidationPrice || 0);
      if (!liq || !latest) return NaN;
      if (side === 'short') return (liq / latest - 1) * 100;
      if (side === 'long') return (1 - liq / latest) * 100;
      return NaN;
    }}
    function addMarginText(stop, latest) {{
      const distancePct = Math.abs(pct(stop, latest));
      return `本次最大保证金：${{fmtPrice(positionConfig.sprintSingleRisk * 6)}} USDT；止损距离约 ${{fmtPct(distancePct)}}，距离越大保证金必须越小`;
    }}
    function currentPositionPlanKey() {{
      const side = positionConfig.activeSide || 'flat';
      const qty = Number(positionConfig.activeQty || 0).toFixed(6);
      const entry = Number(positionConfig.activeEntry || 0).toFixed(1);
      const margin = Number(positionConfig.initialMargin || 0).toFixed(2);
      const liq = Number(positionConfig.liquidationPrice || 0).toFixed(1);
      return `${{side}}|${{qty}}|${{entry}}|${{margin}}|${{liq}}`;
    }}
    function riskAdjustedMarginText(side, stop, latest) {{
      const liq = Number(positionConfig.liquidationPrice || 0);
      const liqGap = calcLiqGap(side, latest);
      if (side === 'short' && liq && stop >= liq * 0.995) {{
        return '风险过高：止损已经贴近强平价，先减仓或补保证金，不给加仓建议';
      }}
      if (side === 'long' && liq && stop <= liq * 1.005) {{
        return '风险过高：止损已经贴近强平价，先减仓或补保证金，不给加仓建议';
      }}
      if (Number.isFinite(liqGap) && liqGap < 1.5) {{
        return '风险过高：距离强平过近，先减仓，不执行加仓计划';
      }}
      return addMarginText(stop, latest);
    }}
    function buildShortPlan(latest, support, resistance) {{
      const entry = Number(positionConfig.activeEntry || positionConfig.shortEntry || latest);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const midRange = (support + resistance) / 2;
      const tp1 = Math.min(entry, latest * 0.992, midRange);
      const tp2 = Math.min(support, tp1 * 0.992);
      const tp3 = Math.min(support * 0.985, tp2 * 0.99);
      const stopCandidates = [resistance * 1.002, latest * 1.008, entry * 1.018];
      if (liq > latest) stopCandidates.push(liq * 0.985);
      const stop = validPrice(Math.min(...stopCandidates.filter(v => Number.isFinite(v) && v > latest)), resistance * 1.002);
      const add1 = Math.max(resistance * 0.996, latest * 1.002);
      const add2 = Math.max(resistance * 1.002, add1 * 1.004);
      const breakdown = Math.min(support * 0.998, latest * 0.996);
      const reverseLong1 = Math.min(support * 1.001, latest * 0.995);
      const reverseLong2 = Math.min(support * 0.985, reverseLong1 * 0.99);
      return {{
        side: 'short',
        tp1, tp2, tp3, stop,
        supportSnapshot: support,
        resistanceSnapshot: resistance,
        takeProfit: `${{fmtPrice(tp1)}} / ${{fmtPrice(tp2)}} / ${{fmtPrice(tp3)}} 空单分批止盈，第一档先减30%-40%`,
        stopLoss: `${{fmtPrice(stop)}} 空单硬止损；若15分钟收盘站上 ${{fmtPrice(resistance)}}，先减仓或离场`,
        shortEntry: `加空：反弹 ${{fmtPrice(add1)}} - ${{fmtPrice(add2)}} 受阻再加；跌破 ${{fmtPrice(breakdown)}} 后回抽不破可追空`,
        longEntry: `反手开多：仅在 ${{fmtPrice(reverseLong1)}} - ${{fmtPrice(reverseLong2)}} 支撑企稳，或15分钟站上 ${{fmtPrice(resistance)}} 后回踩不破再开多`,
        margin: riskAdjustedMarginText('short', stop, latest),
      }};
    }}
    function buildLongPlan(latest, support, resistance) {{
      const entry = Number(positionConfig.activeEntry || positionConfig.longEntry || latest);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const midRange = (support + resistance) / 2;
      const tp1 = Math.max(entry, latest * 1.008, midRange);
      const tp2 = Math.max(resistance, tp1 * 1.008);
      const tp3 = Math.max(resistance * 1.015, tp2 * 1.01);
      const stopCandidates = [support * 0.998, latest * 0.992, entry * 0.982];
      if (liq && liq < latest) stopCandidates.push(liq * 1.015);
      const stop = validPrice(Math.max(...stopCandidates.filter(v => Number.isFinite(v) && v < latest)), support * 0.998);
      const add1 = Math.min(support * 1.004, latest * 0.998);
      const add2 = Math.min(support * 0.998, add1 * 0.996);
      const breakout = Math.max(resistance * 1.002, latest * 1.004);
      const reverseShort1 = Math.max(resistance * 0.999, latest * 1.004);
      const reverseShort2 = Math.max(resistance * 1.006, reverseShort1 * 1.004);
      return {{
        side: 'long',
        tp1, tp2, tp3, stop,
        supportSnapshot: support,
        resistanceSnapshot: resistance,
        takeProfit: `${{fmtPrice(tp1)}} / ${{fmtPrice(tp2)}} / ${{fmtPrice(tp3)}} 多单分批止盈，第一档先减30%-40%`,
        stopLoss: `${{fmtPrice(stop)}} 多单硬止损；若15分钟收盘跌破 ${{fmtPrice(support)}}，先减仓或离场`,
        shortEntry: `反手开空：反弹 ${{fmtPrice(reverseShort1)}} - ${{fmtPrice(reverseShort2)}} 失败，或跌破 ${{fmtPrice(support)}} 后回抽不破再开空`,
        longEntry: `加多：回踩 ${{fmtPrice(add1)}} - ${{fmtPrice(add2)}} 企稳再加；突破 ${{fmtPrice(breakout)}} 后回踩不破可追多`,
        margin: riskAdjustedMarginText('long', stop, latest),
      }};
    }}
    function buildFlatPlan(latest, support, resistance) {{
      const warning = latestEarlyWarning || {{}};
      const atr = Math.max(Number((latestStrategySnapshot && v5BuildMetrics(latestStrategySnapshot).atr15m) || strategyConfig.atr15m || latest * 0.003), latest * 0.0015);
      const longWatch = validPrice(Number(warning.longWatch), Math.min(support * 1.002, latest * 0.996));
      const longConfirm = validPrice(Number(warning.longBreak), Math.max(resistance * 1.001, latest + atr * 0.15));
      const shortWatch = validPrice(Number(warning.shortWatch), Math.max(resistance * 0.998, latest * 1.002));
      const shortConfirm = validPrice(Number(warning.shortBreak), Math.min(support * 0.999, latest - atr * 0.15));
      const invalidLong = validPrice(Number(warning.invalidLong), support - atr * 0.25);
      const invalidShort = validPrice(Number(warning.invalidShort), resistance + atr * 0.25);
      return {{
        takeProfit: '暂无持仓，不给持仓止盈；先等开仓触发后再生成止盈目标',
        stopLoss: '暂无持仓，不给持仓止损；新仓必须先确定止损再决定保证金',
        shortEntry: `提前做空观察位：${{fmtPrice(shortWatch)}} 受阻或 ${{fmtPrice(shortConfirm)}} 跌破前预警；确认触发位：跌破后回抽不破；失效条件：重新站上 ${{fmtPrice(invalidShort)}}`,
        longEntry: `提前做多观察位：${{fmtPrice(longWatch)}} 企稳或 ${{fmtPrice(longConfirm)}} 突破前预警；确认触发位：站上后回踩不破；失效条件：重新跌破 ${{fmtPrice(invalidLong)}}`,
        margin: `本次最大保证金：${{fmtPrice(positionConfig.sprintSingleRisk * 6)}} USDT；${{warning.warningMode || '预警仅用于提前观察，不等于满仓执行'}}`,
      }};
    }}
    function getOrBuildLockedPositionPlan(latest, support, resistance) {{
      const key = currentPositionPlanKey();
      if (lockedPositionPlan && lockedPositionPlanKey === key) return lockedPositionPlan;
      lockedPositionPlanKey = key;
      lockedPositionPlan = positionConfig.activeSide === 'short'
        ? buildShortPlan(latest, support, resistance)
        : buildLongPlan(latest, support, resistance);
      lockedPositionPlan.createdAt = fmtTime(new Date());
      return lockedPositionPlan;
    }}
    function triggerStatusText(plan, latest) {{
      if (!plan || !plan.side) return '等待计划生成';
      if (plan.side === 'flat') return '无仓观察中：开多/开空触发区会随实时支撑阻力刷新';
      const tpDistance = plan.side === 'short' ? latest - plan.tp1 : plan.tp1 - latest;
      const stopDistance = plan.side === 'short' ? plan.stop - latest : latest - plan.stop;
      const tpText = tpDistance <= 0 ? '已触及第一止盈区' : `距离第一止盈 ${{fmtPrice(tpDistance)}} USDT`;
      const stopText = stopDistance <= 0 ? '已触及止损区' : `距离止损 ${{fmtPrice(stopDistance)}} USDT`;
      return `${{tpText}} · ${{stopText}} · 核心点位已锁定，仓位变化才重算`;
    }}
    function updateSimplePlan(latest, support, resistance, source) {{
      liveLatest = Number(latest || liveLatest || 0);
      latest = liveLatest;
      support = validPrice(Number(support), latest * 0.99);
      resistance = validPrice(Number(resistance), latest * 1.01);
      const side = positionConfig.activeSide;
      const entry = Number(positionConfig.activeEntry || 0);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const hasPosition = side !== 'flat' && Number(positionConfig.activeQty || 0) > 0;
      const plan = hasPosition ? getOrBuildLockedPositionPlan(latest, support, resistance) : buildFlatPlan(latest, support, resistance);
      if (!hasPosition) {{
        lockedPositionPlan = null;
        lockedPositionPlanKey = '';
      }}
      const liqGap = calcLiqGap(side, latest);
      setText('simpleCurrentPoint', fmtPrice(latest));
      setText('simpleTakeProfit', plan.takeProfit);
      setText('simpleStopLoss', plan.stopLoss);
      setText('simpleShortEntry', plan.shortEntry);
      setText('simpleLongEntry', plan.longEntry);
      setText('simpleMarginBudget', plan.margin);
      setText('simpleTriggerStatus', triggerStatusText(hasPosition ? plan : {{ side: 'flat' }}, latest));
      const context = side === 'flat'
        ? `支撑 ${{fmtPrice(support)}} · 阻力 ${{fmtPrice(resistance)}} · 当前无仓 · 数据源：${{source}}`
        : `计划锁定于 ${{plan.createdAt || '-'}} · 支撑快照 ${{fmtPrice(plan.supportSnapshot)}} · 阻力快照 ${{fmtPrice(plan.resistanceSnapshot)}} · 开仓均价 ${{fmtPrice(entry)}} · 强平 ${{fmtPrice(liq)}} · 距强平 ${{Number.isFinite(liqGap) ? liqGap.toFixed(2) + '%' : '-'}} · 行情源：${{source}}`;
      setText('simplePlanContext', context);
      setText('liveHeaderMeta', `本次刷新：${{fmtTime(new Date())}} 北京时间 · 标的：BTCUSDT · 数据源：${{source}}`);
      updatePositionUi(latest);
    }}
    function strategyTrendConclusion(emaText, rsi4h) {{
      const rsi = Number(rsi4h);
      if (/多|上方|bull/i.test(String(emaText)) && rsi >= 50) return `${{emaText}}；大方向偏多。`;
      if (/空|下方|bear/i.test(String(emaText)) && rsi <= 50) return `${{emaText}}；大方向偏空。`;
      if (rsi >= 58) return `${{emaText}}；4小时RSI ${{rsi.toFixed(1)}}，多头占优。`;
      if (rsi <= 42) return `${{emaText}}；4小时RSI ${{rsi.toFixed(1)}}，空头占优。`;
      return `${{emaText}}；4小时RSI ${{Number.isFinite(rsi) ? rsi.toFixed(1) : '-'}}，大方向偏震荡。`;
    }}
    function strategyMomentumConclusion(macd1h, macd15m) {{
      const h1 = Number(macd1h);
      const m15 = Number(macd15m);
      if (h1 > 0 && m15 > 0) return `短线偏多，回踩不破更适合找多。`;
      if (h1 < 0 && m15 < 0) return `短线偏空，反弹不过更适合找空。`;
      if (h1 < 0 && m15 > 0) return `15分钟在反弹，但1小时仍偏空；多单只适合轻仓试探。`;
      if (h1 > 0 && m15 < 0) return `15分钟转弱，但1小时仍偏多；空单只适合短打。`;
      return `短线动能不清晰，先等下一根短周期K线。`;
    }}
    function strategyVolumeConclusion(volumeRatio15m, volumeRatio1h, priceVsVwapPct) {{
      const v15 = Number(volumeRatio15m);
      const v1h = Number(volumeRatio1h);
      const vs = Number(priceVsVwapPct);
      if (v15 >= 1.35 && vs > 0) return `放量站上VWAP，短线买盘更主动。`;
      if (v15 >= 1.35 && vs < 0) return `放量跌破VWAP，短线卖盘更主动。`;
      if (v15 < 0.8 && v1h < 0.9) return `量能偏弱，当前突破或反弹可信度不足。`;
      if (vs > 0) return `价格在VWAP上方，买盘略占优。`;
      if (vs < 0) return `价格在VWAP下方，卖盘略占优。`;
      return `量价中性，先看支撑阻力能否被有效突破。`;
    }}
    function strategyFundingConclusion(funding) {{
      const f = Number(funding);
      if (!Number.isFinite(f)) return `资金费率暂无有效值。`;
      if (f >= 0.03) return `资金费率 ${{fmtPct(f)}}，多头明显拥挤。`;
      if (f >= 0.01) return `资金费率 ${{fmtPct(f)}}，多头略拥挤。`;
      if (f <= -0.03) return `资金费率 ${{fmtPct(f)}}，空头明显拥挤。`;
      if (f <= -0.01) return `资金费率 ${{fmtPct(f)}}，空头略拥挤。`;
      return `资金费率 ${{fmtPct(f)}}，资金情绪温和。`;
    }}
    function updateLiveStrategyBasis(snapshot) {{
      const c15 = snapshot.c15 || [];
      const latest = Number(snapshot.latest || 0);
      const recent = c15.slice(-24);
      const volumeBase = c15.slice(-33, -1).reduce((a, c) => a + c.quoteVolume, 0) / Math.max(c15.slice(-33, -1).length, 1);
      const latestVolume = recent.length ? recent[recent.length - 1].quoteVolume : 0;
      const volumeRatio = volumeBase ? latestVolume / volumeBase : strategyConfig.volumeRatio15m;
      const vwap = recent.reduce((acc, c) => acc + ((c.high + c.low + c.close) / 3) * c.quoteVolume, 0) / Math.max(recent.reduce((acc, c) => acc + c.quoteVolume, 0), 1);
      const priceVsVwap = vwap ? pct(latest, vwap) : strategyConfig.priceVsVwapPct;
      const funding = Number(snapshot.funding);
      const cards = [
        ['大方向', strategyTrendConclusion(strategyConfig.emaState4h, strategyConfig.rsi4h)],
        ['短线动能', strategyMomentumConclusion(strategyConfig.macdHist1h, strategyConfig.macdHist15m)],
        ['量价关系', strategyVolumeConclusion(volumeRatio, strategyConfig.volumeRatio1h, priceVsVwap)],
        ['资金费率', strategyFundingConclusion(Number.isFinite(funding) ? funding : strategyConfig.fundingRatePct)]
      ];
      const host = document.getElementById('strategyCards');
      if (host) {{
        host.innerHTML = cards.map(([title, body]) => `<div class="reason-card"><div class="reason-title">${{title}}</div><p>${{body}}</p></div>`).join('');
      }}
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
      const c1m = snapshot.c1m || [];
      const c5m = snapshot.c5m || [];
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
      setText('livePriceSource', `${{snapshot.source}} · ${{fmtTime(new Date())}}`);
      setText('liveChange15m', fmtPct(pct(latest, c15.length >= 2 ? c15[c15.length - 2].close : latest)));
      setText('liveChange1h', fmtPct(pct(latest, c1h.length >= 2 ? c1h[c1h.length - 2].close : latest)));
      setText('liveChange4h', fmtPct(pct(latest, c4h.length >= 2 ? c4h[c4h.length - 2].close : latest)));
      setText('liveChange24h', fmtPct(pct(latest, c15.length >= 96 ? c15[c15.length - 96].close : c1h.length >= 24 ? c1h[c1h.length - 24].close : c4h.length >= 6 ? c4h[c4h.length - 6].close : latest)));
      setText('liveFunding', fmtPct(snapshot.funding));
      setText('liveOpenInterest', fmtPrice(snapshot.openInterest));
      setText('liveStructure', `短线支撑：${{fmtPrice(support)}} · 短线阻力：${{fmtPrice(resistance)}} · 15分钟波动：${{fmtPct(vol)}} · 成交量倍率：${{volumeRatio.toFixed(2)}}x · 数据：${{snapshot.source}}`);
      updateLiveStrategyBasis({{ ...snapshot, c1m, c5m }});
      updateSimplePlan(latest, support, resistance, snapshot.source);
      setText('liveFetchMeta', `实时抓取状态：成功 · ${{snapshot.source}} · 标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}} · 模式：${{reason}}`);
      const status = document.getElementById('liveStatus');
      if (status) status.innerHTML = `<li>本次已现场获取行情；数据源：${{snapshot.source}}；触发方式：${{reason}}；手机端会在OKX失败后自动尝试Binance和Bybit。</li>`;
    }}
    async function fetchBinanceSnapshot() {{
      const [premium, c1mRaw, c5mRaw, c15Raw, c1hRaw, c4hRaw, oiRaw] = await Promise.all([
        fetchAbsoluteJson('Binance mark price', ['https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT']),
        fetchAbsoluteJson('Binance 1m candles', ['https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1m&limit=120']),
        fetchAbsoluteJson('Binance 5m candles', ['https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=5m&limit=120']),
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
        c1m: parseForwardCandles(c1mRaw || []),
        c5m: parseForwardCandles(c5mRaw || []),
        c15: parseForwardCandles(c15Raw || []),
        c1h: parseForwardCandles(c1hRaw || []),
        c4h: parseForwardCandles(c4hRaw || [])
      }};
    }}
    async function fetchBybitSnapshot() {{
      const [ticker, c1mRaw, c5mRaw, c15Raw, c1hRaw, c4hRaw] = await Promise.all([
        fetchAbsoluteJson('Bybit ticker', ['https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT']),
        fetchAbsoluteJson('Bybit 1m candles', ['https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=1&limit=120']),
        fetchAbsoluteJson('Bybit 5m candles', ['https://api.bybit.com/v5/market/kline?category=linear&symbol=BTCUSDT&interval=5&limit=120']),
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
        c1m: parseReverseCandles((c1mRaw.result && c1mRaw.result.list) || []),
        c5m: parseReverseCandles((c5mRaw.result && c5mRaw.result.list) || []),
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
        const [c1mj, c5mj, c15j, c1hj, c4hj, fundingResult, oiResult, mj] = await Promise.all([
          fetchJson('1m candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1m&limit=120'),
          fetchJson('5m candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=5m&limit=120'),
          fetchJson('15m candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=15m&limit=96'),
          fetchJson('1h candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=1H&limit=24'),
          fetchJson('4h candles', '/api/v5/market/candles?instId=BTC-USDT-SWAP&bar=4H&limit=8'),
          fetchJsonSoft('funding', '/api/v5/public/funding-rate?instId=BTC-USDT-SWAP'),
          fetchJsonSoft('open interest', '/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP'),
          fetchJson('mark price', '/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP')
        ]);
        const c1m = parseCandles(c1mj.data || []);
        const c5m = parseCandles(c5mj.data || []);
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
        setText('livePriceSource', `OKX REST现场抓取 · ${{fmtTime(new Date())}}`);
        setText('liveChange15m', fmtPct(pct(latest, c15.length >= 2 ? c15[c15.length - 2].close : latest)));
        setText('liveChange1h', fmtPct(pct(latest, c1h.length >= 2 ? c1h[c1h.length - 2].close : latest)));
        setText('liveChange4h', fmtPct(pct(latest, c4h.length >= 2 ? c4h[c4h.length - 2].close : latest)));
        setText('liveChange24h', fmtPct(pct(latest, c15.length >= 96 ? c15[c15.length - 96].close : c1h.length >= 24 ? c1h[c1h.length - 24].close : c4h.length >= 6 ? c4h[c4h.length - 6].close : latest)));
        setText('liveFunding', fmtPct(funding));
        setText('liveOpenInterest', fmtPrice(openInterest));
        setText('liveStructure', `短线支撑：${{fmtPrice(support)}} · 短线阻力：${{fmtPrice(resistance)}} · 15分钟波动：${{fmtPct(vol)}} · 成交量倍率：${{volumeRatio.toFixed(2)}}x · 数据：浏览器现场抓取`);
        updateLiveStrategyBasis({{ latest, funding, openInterest, c1m, c5m, c15, c1h, c4h, source: 'OKX REST现场抓取' }});
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
              {{ channel: 'candle1m', instId: 'BTC-USDT-SWAP' }},
              {{ channel: 'candle5m', instId: 'BTC-USDT-SWAP' }},
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
                setText('livePriceSource', `OKX WebSocket实时推送 · ${{fmtTime(new Date())}}`);
                updateSimplePlan(latest, liveSupport, liveResistance, 'OKX WebSocket实时推送');
                refreshAccountSoon('websocket-price-sync');
                setText('liveFetchMeta', `实时抓取状态：WebSocket成功 · OKX标记价 ${{fmtPrice(latest)}} · 本机时间 ${{fmtTime(new Date())}}`);
              }}
            }}
            if ((arg.channel === 'candle1m' || arg.channel === 'candle5m') && Array.isArray(row)) {{
              const high = Number(row[2]);
              const low = Number(row[3]);
              const close = Number(row[4]);
              const quoteVolume = Number(row[7] || row[6] || row[5] || 0);
              if (Number.isFinite(high) && Number.isFinite(low) && close > 0) {{
                const candle = {{ high, low, close, quoteVolume }};
                if (arg.channel === 'candle1m') liveEarlyCandles1m = [...liveEarlyCandles1m.slice(-159), candle];
                if (arg.channel === 'candle5m') liveEarlyCandles5m = [...liveEarlyCandles5m.slice(-159), candle];
                if (latestStrategySnapshot) {{
                  updateLiveStrategyBasis({{
                    ...latestStrategySnapshot,
                    latest: close,
                    c1m: liveEarlyCandles1m,
                    c5m: liveEarlyCandles5m,
                    source: 'OKX WebSocket短周期预警'
                  }});
                }}
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
    // V5 realtime risk, strategy scoring, lifecycle-locked position plan, and macro refresh.
    const macroWorkerBaseUrl = accountWorkerUrl && accountWorkerUrl.endsWith('/') ? accountWorkerUrl.slice(0, -1) : accountWorkerUrl;
    const macroWorkerUrl = macroWorkerBaseUrl ? `${{macroWorkerBaseUrl}}/macro` : '';
    let latestStrategySnapshot = null;
    let liveEarlyCandles1m = [];
    let liveEarlyCandles5m = [];
    let latestEarlyWarning = {{ longWarningScore: 0, shortWarningScore: 0, warningMode: '等待1m/5m数据', warningReason: '' }};

    function v5Clamp(value, min, max) {{ return Math.max(min, Math.min(max, value)); }}
    function v5Closes(candles) {{ return (candles || []).map(c => Number(c.close || 0)).filter(v => Number.isFinite(v) && v > 0); }}
    function v5Sma(values, length) {{
      const chunk = values.slice(-length);
      return chunk.length ? chunk.reduce((a, b) => a + b, 0) / chunk.length : 0;
    }}
    function v5EmaSeries(values, length) {{
      if (!values.length) return [];
      const alpha = 2 / (length + 1);
      const result = [values[0]];
      for (let i = 1; i < values.length; i += 1) result.push(values[i] * alpha + result[result.length - 1] * (1 - alpha));
      return result;
    }}
    function v5Ema(values, length) {{
      const series = v5EmaSeries(values, length);
      return series.length ? series[series.length - 1] : 0;
    }}
    function v5Rsi(values, length = 14) {{
      if (values.length <= length) return 50;
      let gain = 0, loss = 0;
      const slice = values.slice(-length - 1);
      for (let i = 1; i < slice.length; i += 1) {{
        const diff = slice[i] - slice[i - 1];
        if (diff >= 0) gain += diff; else loss += Math.abs(diff);
      }}
      const avgGain = gain / length;
      const avgLoss = loss / length;
      if (!avgLoss) return avgGain ? 100 : 50;
      return 100 - (100 / (1 + avgGain / avgLoss));
    }}
    function v5Macd(values) {{
      if (values.length < 35) return {{ line: 0, signal: 0, hist: 0 }};
      const fast = v5EmaSeries(values, 12);
      const slow = v5EmaSeries(values, 26);
      const lineSeries = fast.map((v, i) => v - slow[i]);
      const signalSeries = v5EmaSeries(lineSeries, 9);
      const line = lineSeries[lineSeries.length - 1] || 0;
      const signal = signalSeries[signalSeries.length - 1] || 0;
      return {{ line, signal, hist: line - signal }};
    }}
    function v5Atr(candles, length = 14) {{
      if (!candles || candles.length < 2) return 0;
      const slice = candles.slice(-length - 1);
      const ranges = [];
      for (let i = 1; i < slice.length; i += 1) {{
        const current = slice[i];
        const prev = slice[i - 1];
        ranges.push(Math.max(current.high - current.low, Math.abs(current.high - prev.close), Math.abs(current.low - prev.close)));
      }}
      return ranges.length ? ranges.reduce((a, b) => a + b, 0) / ranges.length : 0;
    }}
    function v5Vwap(candles) {{
      let numerator = 0, denominator = 0;
      (candles || []).forEach(c => {{
        const volume = Number(c.quoteVolume || 0);
        const typical = (Number(c.high || 0) + Number(c.low || 0) + Number(c.close || 0)) / 3;
        numerator += typical * volume;
        denominator += volume;
      }});
      return denominator ? numerator / denominator : 0;
    }}
    function v5VolumeRatio(candles, length = 20) {{
      if (!candles || candles.length < 2) return 1;
      const previous = candles.slice(0, -1).slice(-length);
      const base = previous.reduce((a, c) => a + Number(c.quoteVolume || 0), 0) / Math.max(previous.length, 1);
      return base ? Number(candles[candles.length - 1].quoteVolume || 0) / base : 1;
    }}
    function v5EmaState(candles) {{
      const closes = v5Closes(candles);
      const latest = closes[closes.length - 1] || 0;
      const e20 = v5Ema(closes, 20), e60 = v5Ema(closes, 60), e120 = v5Ema(closes, 120);
      if (latest > e20 && e20 > e60 && e60 > e120) return {{ text: 'EMA多头排列', e20, e60, e120 }};
      if (latest < e20 && e20 < e60 && e60 < e120) return {{ text: 'EMA空头排列', e20, e60, e120 }};
      if (latest > e20 && e20 > e60) return {{ text: 'EMA偏多', e20, e60, e120 }};
      if (latest < e20 && e20 < e60) return {{ text: 'EMA偏空', e20, e60, e120 }};
      return {{ text: 'EMA震荡', e20, e60, e120 }};
    }}
    function v5IsHigherLows(candles, count = 3) {{
      const slice = (candles || []).slice(-count);
      return slice.length >= count && slice.every((c, i) => i === 0 || Number(c.low) > Number(slice[i - 1].low));
    }}
    function v5IsLowerHighs(candles, count = 3) {{
      const slice = (candles || []).slice(-count);
      return slice.length >= count && slice.every((c, i) => i === 0 || Number(c.high) < Number(slice[i - 1].high));
    }}
    function v5RsiSlope(values, length = 14) {{
      if (values.length < length + 5) return 0;
      const recent = [];
      for (let i = 4; i >= 0; i -= 1) {{
        recent.push(v5Rsi(values.slice(0, values.length - i), length));
      }}
      return recent[recent.length - 1] - recent[0];
    }}
    function v5VolumeSlope(candles, length = 20) {{
      if (!candles || candles.length < 4) return 1;
      const previous = candles.slice(0, -3).slice(-length);
      const base = previous.reduce((a, c) => a + Number(c.quoteVolume || 0), 0) / Math.max(previous.length, 1);
      const recent = candles.slice(-3).reduce((a, c) => a + Number(c.quoteVolume || 0), 0) / 3;
      return base ? recent / base : 1;
    }}
    function v5BuildEarlyMetrics(snapshot, confirmMetrics) {{
      const c1m = (snapshot.c1m && snapshot.c1m.length ? snapshot.c1m : liveEarlyCandles1m) || [];
      const c5m = (snapshot.c5m && snapshot.c5m.length ? snapshot.c5m : liveEarlyCandles5m) || [];
      if (c1m.length) liveEarlyCandles1m = c1m.slice(-160);
      if (c5m.length) liveEarlyCandles5m = c5m.slice(-160);
      const latest = Number(confirmMetrics.latest || snapshot.latest || liveLatest || 0);
      const closes1m = v5Closes(c1m);
      const closes5m = v5Closes(c5m);
      const ema20_5m = v5Ema(closes5m, 20);
      const vwap5m = v5Vwap(c5m.slice(-60));
      const rsiSlope1m = v5RsiSlope(closes1m);
      const rsiSlope5m = v5RsiSlope(closes5m);
      const volSlope1m = v5VolumeSlope(c1m);
      const volSlope5m = v5VolumeSlope(c5m);
      const atrGate = Math.max(Number(confirmMetrics.atr15m || 0) * 0.25, latest * 0.001);
      const distanceToResistance = Math.abs(confirmMetrics.resistance - latest);
      const distanceToSupport = Math.abs(latest - confirmMetrics.support);
      const nearResistance = distanceToResistance <= atrGate;
      const nearSupport = distanceToSupport <= atrGate;
      const last15 = (snapshot.c15 || []).slice(-1)[0] || null;
      return {{
        latest,
        hasEarlyData: c1m.length >= 5 || c5m.length >= 5,
        c1m,
        c5m,
        higherLows1m: v5IsHigherLows(c1m),
        higherLows5m: v5IsHigherLows(c5m),
        lowerHighs1m: v5IsLowerHighs(c1m),
        lowerHighs5m: v5IsLowerHighs(c5m),
        rsiSlope1m,
        rsiSlope5m,
        volSlope1m,
        volSlope5m,
        ema20_5m,
        vwap5m,
        nearResistance,
        nearSupport,
        atrGate,
        support: confirmMetrics.support,
        resistance: confirmMetrics.resistance,
        atr15m: confirmMetrics.atr15m,
        fifteenBreakoutUp: Boolean(last15 && latest > Math.max(Number(last15.high || 0), confirmMetrics.resistance)),
        fifteenBreakoutDown: Boolean(last15 && latest < Math.min(Number(last15.low || Infinity), confirmMetrics.support)),
      }};
    }}
    function v5EarlyWarningScore(early, confirmMetrics, confirmScore) {{
      let longWarningScore = 25;
      let shortWarningScore = 25;
      const reasons = [];
      if (early.nearResistance) {{ longWarningScore += 10; reasons.push('价格进入阻力临界区，观察突破前动作'); }}
      if (early.nearSupport) {{ shortWarningScore += 10; reasons.push('价格进入支撑临界区，观察跌破前动作'); }}
      if (early.higherLows1m) longWarningScore += 10;
      if (early.higherLows5m) {{ longWarningScore += 16; reasons.push('5分钟连续抬高低点，多头预热'); }}
      if (early.lowerHighs1m) shortWarningScore += 10;
      if (early.lowerHighs5m) {{ shortWarningScore += 16; reasons.push('5分钟连续降低高点，空头预热'); }}
      if (early.rsiSlope1m > 4 || early.rsiSlope5m > 4) {{ longWarningScore += 12; reasons.push('短周期RSI连续回升'); }}
      if (early.rsiSlope1m < -4 || early.rsiSlope5m < -4) {{ shortWarningScore += 12; reasons.push('短周期RSI连续回落'); }}
      if (early.volSlope5m > 1.25 && early.latest >= early.vwap5m) longWarningScore += 10;
      if (early.volSlope5m > 1.25 && early.latest <= early.vwap5m) shortWarningScore += 10;
      if (!early.hasEarlyData) {{
        return {{
          longWarningScore: 0,
          shortWarningScore: 0,
          warningMode: '等待1m/5m数据',
          warningReason: '短周期预警数据尚未就绪',
          longWatch: confirmMetrics.support,
          longBreak: confirmMetrics.resistance,
          shortWatch: confirmMetrics.resistance,
          shortBreak: confirmMetrics.support,
          invalidLong: confirmMetrics.support - confirmMetrics.atr15m * 0.25,
          invalidShort: confirmMetrics.resistance + confirmMetrics.atr15m * 0.25,
        }};
      }}
      if (early.vwap5m && early.ema20_5m && early.latest > early.vwap5m && early.latest > early.ema20_5m) longWarningScore += 8;
      if (early.vwap5m && early.ema20_5m && early.latest < early.vwap5m && early.latest < early.ema20_5m) shortWarningScore += 8;
      if (early.fifteenBreakoutUp) longWarningScore += 12;
      if (early.fifteenBreakoutDown) shortWarningScore += 12;
      longWarningScore = v5Clamp(Math.round(longWarningScore), 0, 100);
      shortWarningScore = v5Clamp(Math.round(shortWarningScore), 0, 100);
      let warningMode = '等待预警';
      if (longWarningScore >= 70 && confirmScore.longScore < 62) warningMode = '多头预警，不是确认；轻仓或等下一根短周期K线';
      else if (shortWarningScore >= 70 && confirmScore.shortScore < 62) warningMode = '空头预警，不是确认；轻仓或等下一根短周期K线';
      else if (longWarningScore >= 70 && confirmScore.longScore >= 62) warningMode = '多头预警已转确认，可执行计划';
      else if (shortWarningScore >= 70 && confirmScore.shortScore >= 62) warningMode = '空头预警已转确认，可执行计划';
      else if (longWarningScore > shortWarningScore + 12) warningMode = '多头预热';
      else if (shortWarningScore > longWarningScore + 12) warningMode = '空头预热';
      const longWatch = Math.min(early.support + early.atr15m * 0.35, early.vwap5m || early.latest, early.resistance - early.atr15m * 0.15);
      const longBreak = Math.max(early.resistance - early.atr15m * 0.10, early.latest + early.atr15m * 0.12);
      const shortWatch = Math.max(early.resistance - early.atr15m * 0.35, early.vwap5m || early.latest, early.support + early.atr15m * 0.15);
      const shortBreak = Math.min(early.support + early.atr15m * 0.10, early.latest - early.atr15m * 0.12);
      return {{
        longWarningScore,
        shortWarningScore,
        warningMode,
        warningReason: reasons.slice(0, 3).join('；') || '短周期微结构尚未给出明显提前信号',
        longWatch,
        longBreak,
        shortWatch,
        shortBreak,
        invalidLong: early.support - early.atr15m * 0.25,
        invalidShort: early.resistance + early.atr15m * 0.25,
      }};
    }}
    function updateEarlyWarningUi(warning) {{
      latestEarlyWarning = warning;
      setText('earlyLongWarning', String(warning.longWarningScore));
      setText('earlyShortWarning', String(warning.shortWarningScore));
      setText('earlyWarningMode', `${{warning.warningMode}} · ${{warning.warningReason}}`);
    }}
    function v5BuildMetrics(snapshot) {{
      const c15 = snapshot.c15 || [], c1h = snapshot.c1h || [], c4h = snapshot.c4h || [];
      const latest = Number(snapshot.latest || liveLatest || 0);
      const closes15 = v5Closes(c15), closes1h = v5Closes(c1h), closes4h = v5Closes(c4h);
      const recent24h = c15.length >= 96 ? c15.slice(-96) : c1h.length >= 24 ? c1h.slice(-24) : c4h.slice(-6);
      const supportWindow = c15.length >= 24 ? c15.slice(-24) : c15;
      const support = supportWindow.length ? Math.min(...supportWindow.map(c => Number(c.low || latest))) : liveSupport;
      const resistance = supportWindow.length ? Math.max(...supportWindow.map(c => Number(c.high || latest))) : liveResistance;
      const vwap24h = v5Vwap(recent24h);
      return {{
        latest,
        support,
        resistance,
        rsi15m: v5Rsi(closes15),
        rsi1h: v5Rsi(closes1h),
        rsi4h: v5Rsi(closes4h),
        macd15m: v5Macd(closes15),
        macd1h: v5Macd(closes1h),
        macd4h: v5Macd(closes4h),
        volumeRatio15m: v5VolumeRatio(c15),
        volumeRatio1h: v5VolumeRatio(c1h),
        volumeRatio4h: v5VolumeRatio(c4h),
        ema15m: v5EmaState(c15),
        ema1h: v5EmaState(c1h),
        ema4h: v5EmaState(c4h),
        atr15m: v5Atr(c15),
        atr1h: v5Atr(c1h),
        atr4h: v5Atr(c4h),
        vwap24h,
        priceVsVwapPct: vwap24h ? pct(latest, vwap24h) : 0,
        funding: Number(snapshot.funding),
        openInterest: Number(snapshot.openInterest),
        change15m: pct(latest, closes15.length >= 2 ? closes15[closes15.length - 2] : latest),
        change1h: pct(latest, closes1h.length >= 2 ? closes1h[closes1h.length - 2] : latest),
        change4h: pct(latest, closes4h.length >= 2 ? closes4h[closes4h.length - 2] : latest),
        change24h: pct(latest, recent24h.length ? Number(recent24h[0].close || latest) : latest),
      }};
    }}
    function v5Score(metrics) {{
      let longScore = 35, shortScore = 35, riskScore = 20;
      const reasons = [];
      if (metrics.rsi4h > 55) {{ longScore += 14; reasons.push(`4小时RSI ${{metrics.rsi4h.toFixed(1)}}，大方向偏多`); }}
      else if (metrics.rsi4h < 45) {{ shortScore += 14; reasons.push(`4小时RSI ${{metrics.rsi4h.toFixed(1)}}，大方向偏空`); }}
      else reasons.push(`4小时RSI ${{metrics.rsi4h.toFixed(1)}}，方向优势不明显`);
      if (metrics.macd1h.hist > 0) longScore += 16; else if (metrics.macd1h.hist < 0) shortScore += 16;
      if (metrics.macd15m.hist > 0 && metrics.volumeRatio15m > 1.2) longScore += 10;
      if (metrics.macd15m.hist < 0 && metrics.volumeRatio15m > 1.2) shortScore += 10;
      if (['EMA多头排列', 'EMA偏多'].includes(metrics.ema4h.text)) longScore += 12;
      if (['EMA空头排列', 'EMA偏空'].includes(metrics.ema4h.text)) shortScore += 12;
      if (metrics.priceVsVwapPct > 0.25) longScore += 5;
      if (metrics.priceVsVwapPct < -0.25) shortScore += 5;
      if (Number.isFinite(metrics.funding) && metrics.funding > 0.02 && metrics.change1h < 0) shortScore += 8;
      if (Number.isFinite(metrics.funding) && metrics.funding < -0.02 && metrics.change1h > 0) longScore += 8;
      if (Math.abs(metrics.change1h) > 0.7 || Math.abs(metrics.change24h) > 2) riskScore += 15;
      if (metrics.atr15m && metrics.latest && metrics.atr15m / metrics.latest * 100 > 0.6) riskScore += 15;
      const liqGap = calcLiqGap(positionConfig.activeSide, metrics.latest);
      if (Number.isFinite(liqGap) && liqGap < 1.2) riskScore += 60;
      else if (Number.isFinite(liqGap) && liqGap < 3) riskScore += 35;
      if (Math.abs(longScore - shortScore) < 12) riskScore += 15;
      longScore = v5Clamp(Math.round(longScore), 0, 100);
      shortScore = v5Clamp(Math.round(shortScore), 0, 100);
      riskScore = v5Clamp(Math.round(riskScore), 0, 100);
      let tradeMode = '等待确认';
      if (riskScore >= 80) tradeMode = '禁止交易';
      else if (positionConfig.activeSide !== 'flat' && Number(positionConfig.activeQty || 0) > 0) tradeMode = Math.abs(longScore - shortScore) < 18 ? '只管理持仓' : shortScore > longScore ? '只做空' : '只做多';
      else if (longScore >= 62 && longScore - shortScore >= 12) tradeMode = '只做多';
      else if (shortScore >= 62 && shortScore - longScore >= 12) tradeMode = '只做空';
      else if (longScore >= 55 && shortScore >= 55) tradeMode = '多空都可';
      return {{ longScore, shortScore, riskScore, tradeMode, reason: reasons.join('；') }};
    }}
    function v5UpdateStrategyUi(metrics, score) {{
      strategyConfig.longScore = score.longScore;
      strategyConfig.shortScore = score.shortScore;
      strategyConfig.riskScore = score.riskScore;
      strategyConfig.tradeMode = score.tradeMode;
      setText('strategyLongScore', String(score.longScore));
      setText('strategyShortScore', String(score.shortScore));
      setText('strategyRiskScore', String(score.riskScore));
      setText('strategyTradeMode', score.tradeMode);
      setText('strategyReason', score.reason || '等待多周期指标确认');
      const cards = [
        ['大方向', strategyTrendConclusion(metrics.ema4h.text, metrics.rsi4h)],
        ['短线动能', strategyMomentumConclusion(metrics.macd1h.hist, metrics.macd15m.hist)],
        ['量价关系', strategyVolumeConclusion(metrics.volumeRatio15m, metrics.volumeRatio1h, metrics.priceVsVwapPct)],
        ['资金费率', strategyFundingConclusion(Number.isFinite(metrics.funding) ? metrics.funding : 0)],
      ];
      const host = document.getElementById('strategyCards');
      if (host) host.innerHTML = cards.map(([title, body]) => `<div class="reason-card"><div class="reason-title">${{title}}</div><p>${{body}}</p></div>`).join('');
    }}
    updateLiveStrategyBasis = function(snapshot) {{
      latestStrategySnapshot = snapshot;
      const metrics = v5BuildMetrics(snapshot);
      const score = v5Score(metrics);
      const earlyMetrics = v5BuildEarlyMetrics(snapshot, metrics);
      const earlyWarning = v5EarlyWarningScore(earlyMetrics, metrics, score);
      liveSupport = metrics.support;
      liveResistance = metrics.resistance;
      v5UpdateStrategyUi(metrics, score);
      updateEarlyWarningUi(earlyWarning);
      updateSimplePlan(metrics.latest, metrics.support, metrics.resistance, snapshot.source || '实时行情');
    }};

    function v5PlanStorageKey() {{ return 'BTC_LOCKED_POSITION_PLAN_V5'; }}
    function v5StoredPlan() {{
      try {{ return JSON.parse(localStorage.getItem(v5PlanStorageKey()) || 'null'); }} catch {{ return null; }}
    }}
    function v5SavePlan(plan) {{ try {{ localStorage.setItem(v5PlanStorageKey(), JSON.stringify(plan)); }} catch {{ /* ignore storage failure */ }} }}
    function v5ClearPlan() {{ try {{ localStorage.removeItem(v5PlanStorageKey()); }} catch {{ /* ignore storage failure */ }} }}
    function currentPositionPlanKey() {{
      const side = positionConfig.activeSide || 'flat';
      const qty = Number(positionConfig.activeQty || 0);
      const entry = Number(positionConfig.activeEntry || 0);
      if (side === 'flat' || qty <= 0 || entry <= 0) return 'flat';
      return `${{side}}|entry:${{Math.round(entry / Math.max(entry * 0.0015, 1))}}|qty:${{Math.round(qty / Math.max(qty * 0.10, 0.000001))}}`;
    }}
    function v5SameLifecycle(plan) {{
      if (!plan) return false;
      const side = positionConfig.activeSide || 'flat';
      const qty = Number(positionConfig.activeQty || 0);
      const entry = Number(positionConfig.activeEntry || 0);
      if (side === 'flat' || qty <= 0 || entry <= 0) return false;
      if (plan.side !== side) return false;
      if (Math.abs(entry / Number(plan.entry || 0) - 1) > 0.0015) return false;
      if (Math.abs(qty / Number(plan.qty || 0) - 1) > 0.10) return false;
      return true;
    }}
    function v5LockedPlanText(plan) {{
      const sideText = plan.side === 'short' ? '空单' : '多单';
      return `${{fmtPrice(plan.tp1)}} / ${{fmtPrice(plan.tp2)}} / ${{fmtPrice(plan.tp3)}} ${{sideText}}分批止盈，核心点位已锁定`;
    }}
    function buildShortPlan(latest, support, resistance) {{
      const entry = Number(positionConfig.activeEntry || latest);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const atr = Math.max(Number((latestStrategySnapshot && v5BuildMetrics(latestStrategySnapshot).atr15m) || strategyConfig.atr15m || latest * 0.003), latest * 0.0015);
      const structuralSupport = Math.min(support, entry - atr);
      const tp1 = Math.min(structuralSupport, entry - atr * 1.2, entry * 0.992);
      const tp2 = Math.min(tp1 - atr, structuralSupport - atr * 0.8, entry * 0.984);
      const tp3 = Math.min(tp2 - atr * 1.2, entry * 0.968);
      let stop = Math.max(resistance, entry + atr * 1.2, entry * 1.006);
      if (liq > entry) stop = Math.min(stop, liq * 0.985);
      if (stop <= entry) stop = entry + atr * 1.2;
      const add1 = Math.max(resistance * 0.998, entry + atr * 0.7);
      const add2 = Math.max(add1 + atr * 0.8, resistance * 1.002);
      const reverseLong1 = Math.min(tp1, support * 1.001);
      const reverseLong2 = Math.min(tp2, reverseLong1 - atr);
      return {{
        side: 'short', key: currentPositionPlanKey(), entry, qty: Number(positionConfig.activeQty || 0), createdAt: fmtTime(new Date()),
        supportSnapshot: support, resistanceSnapshot: resistance, atrSnapshot: atr, tp1, tp2, tp3, stop, add1, add2, reverseLong1, reverseLong2,
        takeProfit: `${{fmtPrice(tp1)}} / ${{fmtPrice(tp2)}} / ${{fmtPrice(tp3)}} 空单分批止盈，第一档先减30%-40%`,
        stopLoss: `${{fmtPrice(stop)}} 空单硬止损；若15分钟收盘站上锁定阻力 ${{fmtPrice(resistance)}}，先减仓或离场`,
        shortEntry: `加空：反弹 ${{fmtPrice(add1)}} - ${{fmtPrice(add2)}} 受阻再加；跌破 ${{fmtPrice(tp1)}} 后回抽不破可追空`,
        longEntry: `反手开多：仅在 ${{fmtPrice(reverseLong1)}} - ${{fmtPrice(reverseLong2)}} 支撑企稳，或15分钟站上 ${{fmtPrice(resistance)}} 后回踩不破再开多`,
        margin: riskAdjustedMarginText('short', stop, latest),
      }};
    }}
    function buildLongPlan(latest, support, resistance) {{
      const entry = Number(positionConfig.activeEntry || latest);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const atr = Math.max(Number((latestStrategySnapshot && v5BuildMetrics(latestStrategySnapshot).atr15m) || strategyConfig.atr15m || latest * 0.003), latest * 0.0015);
      const structuralResistance = Math.max(resistance, entry + atr);
      const tp1 = Math.max(structuralResistance, entry + atr * 1.2, entry * 1.008);
      const tp2 = Math.max(tp1 + atr, structuralResistance + atr * 0.8, entry * 1.016);
      const tp3 = Math.max(tp2 + atr * 1.2, entry * 1.032);
      let stop = Math.min(support, entry - atr * 1.2, entry * 0.994);
      if (liq && liq < entry) stop = Math.max(stop, liq * 1.015);
      if (stop >= entry) stop = entry - atr * 1.2;
      const add1 = Math.min(support * 1.002, entry - atr * 0.7);
      const add2 = Math.min(add1 - atr * 0.8, support * 0.998);
      const reverseShort1 = Math.max(tp1, resistance * 0.999);
      const reverseShort2 = Math.max(tp2, reverseShort1 + atr);
      return {{
        side: 'long', key: currentPositionPlanKey(), entry, qty: Number(positionConfig.activeQty || 0), createdAt: fmtTime(new Date()),
        supportSnapshot: support, resistanceSnapshot: resistance, atrSnapshot: atr, tp1, tp2, tp3, stop, add1, add2, reverseShort1, reverseShort2,
        takeProfit: `${{fmtPrice(tp1)}} / ${{fmtPrice(tp2)}} / ${{fmtPrice(tp3)}} 多单分批止盈，第一档先减30%-40%`,
        stopLoss: `${{fmtPrice(stop)}} 多单硬止损；若15分钟收盘跌破锁定支撑 ${{fmtPrice(support)}}，先减仓或离场`,
        shortEntry: `反手开空：反弹 ${{fmtPrice(reverseShort1)}} - ${{fmtPrice(reverseShort2)}} 失败，或跌破 ${{fmtPrice(support)}} 后回抽不破再开空`,
        longEntry: `加多：回踩 ${{fmtPrice(add1)}} - ${{fmtPrice(add2)}} 企稳再加；突破 ${{fmtPrice(tp1)}} 后回踩不破可追多`,
        margin: riskAdjustedMarginText('long', stop, latest),
      }};
    }}
    function getOrBuildLockedPositionPlan(latest, support, resistance, force = false) {{
      const stored = v5StoredPlan();
      if (!force && v5SameLifecycle(stored)) {{
        lockedPositionPlan = stored;
        lockedPositionPlanKey = stored.key || currentPositionPlanKey();
        return stored;
      }}
      lockedPositionPlanKey = currentPositionPlanKey();
      lockedPositionPlan = positionConfig.activeSide === 'short'
        ? buildShortPlan(latest, support, resistance)
        : buildLongPlan(latest, support, resistance);
      v5SavePlan(lockedPositionPlan);
      return lockedPositionPlan;
    }}
    function triggerStatusText(plan, latest) {{
      if (!plan || !plan.side) return '等待计划生成';
      if (plan.side === 'flat') return '无仓观察中：开多/开空触发区会随实时支撑阻力刷新';
      const tpDistance = plan.side === 'short' ? latest - plan.tp1 : plan.tp1 - latest;
      const stopDistance = plan.side === 'short' ? plan.stop - latest : latest - plan.stop;
      const tpText = tpDistance <= 0 ? '已触及第一止盈区' : `距离第一止盈 ${{fmtPrice(tpDistance)}} USDT`;
      const stopText = stopDistance <= 0 ? '已触及止损区' : `距离止损 ${{fmtPrice(stopDistance)}} USDT`;
      let supportText = '当前行情仍支持原计划';
      if ((plan.side === 'short' && Number(strategyConfig.longScore || 0) - Number(strategyConfig.shortScore || 0) >= 18) ||
          (plan.side === 'long' && Number(strategyConfig.shortScore || 0) - Number(strategyConfig.longScore || 0) >= 18)) {{
        supportText = '原计划失效风险升高，建议减仓或手动重新锁定';
      }}
      if ((plan.side === 'short' && Number(latestEarlyWarning.longWarningScore || 0) >= 70) ||
          (plan.side === 'long' && Number(latestEarlyWarning.shortWarningScore || 0) >= 70)) {{
        supportText = `反向预警升高：${{latestEarlyWarning.warningMode}}，点位不自动重算`;
      }}
      return `${{tpText}} · ${{stopText}} · ${{supportText}}`;
    }}
    function updateSimplePlan(latest, support, resistance, source) {{
      liveLatest = Number(latest || liveLatest || 0);
      latest = liveLatest;
      support = validPrice(Number(support), latest * 0.99);
      resistance = validPrice(Number(resistance), latest * 1.01);
      const side = positionConfig.activeSide;
      const entry = Number(positionConfig.activeEntry || 0);
      const liq = Number(positionConfig.liquidationPrice || 0);
      const hasPosition = side !== 'flat' && Number(positionConfig.activeQty || 0) > 0;
      const plan = hasPosition ? getOrBuildLockedPositionPlan(latest, support, resistance) : buildFlatPlan(latest, support, resistance);
      if (!hasPosition) {{ lockedPositionPlan = null; lockedPositionPlanKey = ''; v5ClearPlan(); }}
      const liqGap = calcLiqGap(side, latest);
      setText('simpleCurrentPoint', fmtPrice(latest));
      setText('simpleTakeProfit', plan.takeProfit);
      setText('simpleStopLoss', plan.stopLoss);
      setText('simpleShortEntry', plan.shortEntry);
      setText('simpleLongEntry', plan.longEntry);
      setText('simpleMarginBudget', plan.margin);
      setText('simpleTriggerStatus', triggerStatusText(hasPosition ? plan : {{ side: 'flat' }}, latest));
      const context = side === 'flat'
        ? `无仓观察计划 · 支撑 ${{fmtPrice(support)}} · 阻力 ${{fmtPrice(resistance)}} · 行情源：${{source}}`
        : `计划锁定时间 ${{plan.createdAt || '-'}} · 锁定依据：开仓均价 ${{fmtPrice(entry)}} / 支撑快照 ${{fmtPrice(plan.supportSnapshot)}} / 阻力快照 ${{fmtPrice(plan.resistanceSnapshot)}} / ATR ${{fmtPrice(plan.atrSnapshot)}} · 强平 ${{fmtPrice(liq)}} · 距强平 ${{Number.isFinite(liqGap) ? liqGap.toFixed(2) + '%' : '-'}} · 行情源：${{source}}`;
      setText('simplePlanContext', context);
      setText('liveHeaderMeta', `本次刷新：${{fmtTime(new Date())}} 北京时间 · 标的：BTCUSDT · 数据源：${{source}}`);
      updatePositionUi(latest);
    }}
    function v5InstallRelockButton() {{
      const planSection = document.querySelector('section.plan');
      if (!planSection || document.getElementById('relockPlanButton')) return;
      const button = document.createElement('button');
      button.id = 'relockPlanButton';
      button.type = 'button';
      button.textContent = '重新锁定计划';
      button.style.cssText = 'margin:0 0 10px;padding:8px 12px;border:1px solid #475467;border-radius:8px;background:#fff;color:#17202a;font-weight:700;';
      button.addEventListener('click', () => {{
        if (positionConfig.activeSide === 'flat') return;
        const plan = getOrBuildLockedPositionPlan(liveLatest, liveSupport, liveResistance, true);
        v5SavePlan(plan);
        updateSimplePlan(liveLatest, liveSupport, liveResistance, '手动重新锁定');
      }});
      const ref = planSection.querySelector('.plan-lines');
      planSection.insertBefore(button, ref);
    }}
    v5InstallRelockButton();

    applyAccountSnapshot = function(account) {{
      if (!account || !account.ok) return;
      const syncedAt = account.okxFetchedAt || account.workerFetchedAt || account.updatedAt || new Date().toISOString();
      const rate = Number(account.cnyRate || positionConfig.fallbackCnyRate || 7.2);
      const equityUsdt = Number(account.equityUsdt || positionConfig.accountEquity || 0);
      const equityCny = Number(account.equityCny || equityUsdt * rate);
      const weekProfitCny = Number(account.weekProfitCny ?? positionConfig.sprintWeeklyProfitCny ?? 0);
      const weeklyLossLimitCny = Number(account.weeklyLossLimitCny || account.weekRiskCny || positionConfig.sprintWeeklyRiskCny || 0);
      const weeklyStatus = account.weeklyRiskStatus || (weekProfitCny <= -weeklyLossLimitCny ? '本周禁止开新仓，只允许减仓/止损/平仓' : '本周风控正常');
      positionConfig.accountEquity = equityUsdt;
      const sprintStageSync = applySprintStageFromEquity(equityCny, equityUsdt, rate, weeklyLossLimitCny);
      setText('sprintEquityCny', fmtCny(equityCny));
      setText('sprintEquity', `${{fmtMoney2(equityUsdt)}} USDT · 汇率 ${{rate.toFixed(3)}}`);
      setText('sprintWeeklyRisk', `${{weekProfitCny >= 0 ? '+' : ''}}${{fmtCny(weekProfitCny)}} / 最大亏损 ${{fmtCny(sprintStageSync.weeklyLossLimitCny)}}`);
      setText('weeklyRiskStatus', weeklyStatus);
      const hedgeText = account.hasHedgedPositions ? ' · 检测到双向持仓，显示主仓位' : '';
      setText('accountRefreshState', `成功 · ${{fmtTime(new Date(syncedAt))}}${{hedgeText}}`);
      if (account.position) {{
        const p = account.position;
        const side = p.side || positionConfig.activeSide;
        positionConfig.activeSide = side;
        positionConfig.activeQty = Number(p.quantityBtc || positionConfig.activeQty || 0);
        positionConfig.activeEntry = Number(p.entryPrice || positionConfig.activeEntry || 0);
        positionConfig.activeLeverage = Number(p.leverage || 100);
        positionConfig.initialMargin = Number(p.marginUsdt || positionConfig.initialMargin || 0);
        positionConfig.liquidationPrice = Number(p.liquidationPrice || positionConfig.liquidationPrice || 0);
        const badge = document.getElementById('positionSideBadge');
        if (badge) {{
          badge.textContent = side === 'short' ? '空' : side === 'long' ? '多' : '无仓';
          badge.classList.toggle('side-short', side === 'short');
          badge.classList.toggle('side-long', side === 'long');
        }}
        setText('positionLeverage', `${{positionConfig.activeLeverage || 100}}x`);
        setText('positionQty', `${{positionConfig.activeQty || 0}}`);
        setText('positionEntry', fmtPrice(positionConfig.activeEntry));
        setText('positionMargin', fmtPrice(positionConfig.initialMargin));
        setText('positionLiqPrice', fmtPrice(positionConfig.liquidationPrice));
      }} else {{
        positionConfig.activeSide = 'flat';
        positionConfig.activeQty = 0;
        positionConfig.activeEntry = 0;
        positionConfig.initialMargin = 0;
        positionConfig.liquidationPrice = 0;
        v5ClearPlan();
        setText('positionSideBadge', '无仓');
        setText('positionLeverage', '100x');
        setText('positionQty', '0');
        setText('positionEntry', '-');
        setText('positionMargin', '-');
        setText('positionLiqPrice', '-');
      }}
      updateSimplePlan(liveLatest, liveSupport, liveResistance, 'OKX账户实时同步');
    }};

    function v5MacroDirectionSummary(events) {{
      const directional = (events || []).find(event => event.status === '已公布') || (events || [])[0];
      return directional ? directional.btcDirection : '宏观窗口暂不提供明确方向，优先看实时技术评分。';
    }}
    function renderMacroEvent(event) {{
      const eventType = event.type || (String(event.category || '').toLowerCase().includes('crypto') ? '加密政策' : '经济数据');
      return `
        <li>
          <strong>${{fmtTime(new Date(event.scheduledAt))}} 北京时间 · ${{event.title}}</strong>
          <br><span class="small">类型：${{eventType}} · 来源：${{event.source}} · 影响：${{event.impact}} · 状态：${{event.status}}</span>
          <br><span class="small"><strong>预期：</strong>${{event.forecast || '-'}}</span>
          <br><span class="small"><strong>前值：</strong>${{event.previous || '-'}}</span>
          <br><span class="small"><strong>实际值：</strong>${{event.actual || '-'}}</span>
          <br><span class="small"><strong>BTC方向：</strong>${{event.btcDirection}}</span>
        </li>`;
    }}
    async function refreshMacroEvents(reason = 'macro-5m-sync') {{
      if (!macroWorkerUrl) return;
      try {{
        const response = await fetch(withCacheBust(macroWorkerUrl), {{ cache: 'no-store' }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const payload = await response.json();
        if (!payload.ok) throw new Error(payload.error || '宏观接口返回失败');
        const events = payload.events || [];
        const upcoming = (payload.upcomingEvents || events).filter(event => !event.placeholder);
        const recent = (payload.recentReleasedEvents || []).filter(event => !event.placeholder);
        const warnings = payload.warnings || [];
        const macroMode = payload.macroStatus && payload.macroStatus.freeOfficialMode ? '免费官方源' : payload.source;
        setText('macroSummary', `未来24小时 ${{upcoming.length}} 个；最近7天关键消息 ${{recent.length}} 个；数据源：${{macroMode}}；刷新：${{fmtTime(new Date(payload.updatedAt || Date.now()))}}`);
        setText('macroForecast', v5MacroDirectionSummary(recent.length ? recent : upcoming.length ? upcoming : events));
        setText('macroWindow', `窗口：${{fmtTime(new Date(payload.windowStart))}} - ${{fmtTime(new Date(payload.windowEnd))}} 北京时间；已公布关键数据保留7天`);
        setText('macroWarnings', warnings.length ? `数据源状态：${{warnings.join('；')}}` : `数据源状态：${{macroMode}}正常`);
        const list = document.getElementById('macroEventsList');
        if (list) list.innerHTML = upcoming.length ? upcoming.map(renderMacroEvent).join('') : '<li>未来24小时暂无已接入的高影响宏观事件。</li>';
        const recentList = document.getElementById('recentMacroEventsList');
        if (recentList) recentList.innerHTML = recent.length ? recent.map(renderMacroEvent).join('') : '<li>最近7天暂无已接入的关键消息。</li>';
      }} catch (error) {{
        setText('macroSummary', `宏观事件刷新失败：${{String(error).slice(0, 80)}}`);
      }}
    }}

    refreshLiveMarket('page-load');
    refreshAccount('page-load');
    startOkxWebSocket();
    setInterval(() => {{
      if (document.visibilityState !== 'hidden' && !websocketHasLivePrice) refreshLiveMarket('REST-15s-fallback');
    }}, 15000);
    setInterval(() => {{
      if (document.visibilityState !== 'hidden' && websocketHasLivePrice) refreshLiveMarket('REST-15s-score-sync');
    }}, 15000);
    refreshMacroEvents('page-load');
    setInterval(() => {{ if (document.visibilityState !== 'hidden') refreshMacroEvents('macro-5m-sync'); }}, 300000);
    setInterval(() => {{ if (document.visibilityState !== 'hidden') refreshMacroEvents('macro-high-impact-30s-sync'); }}, 30000);
    document.addEventListener('visibilitychange', () => {{ if (document.visibilityState === 'visible') refreshLiveMarket('page-visible'); }});
    document.addEventListener('visibilitychange', () => {{ if (document.visibilityState === 'visible') refreshAccount('page-visible'); }});
    window.addEventListener('focus', () => {{ refreshLiveMarket('window-focus'); refreshAccount('window-focus'); }});
    setInterval(() => {{ if (document.visibilityState !== 'hidden') refreshAccount('account-15s-sync'); }}, 15000);
  </script>
</body>
</html>
"""
