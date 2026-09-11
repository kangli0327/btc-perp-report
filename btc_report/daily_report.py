from __future__ import annotations

import html
import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .advice import Advice
from .config import PositionConfig
from .indicators import Indicators
from .macro_events import MacroBrief
from .render import DEFAULT_ACCOUNT_WORKER_URL, fmt_price


CN_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class DailyReport:
    report_date: str
    generated_at: str
    title: str
    verdict: str
    btc_price: str
    key_levels: str
    strategy: str
    account_note: str
    macro_focus: str
    macro_judgment: str
    sim_note: str
    risk_note: str
    archive_name: str
    source_status: str


def daily_report_date(now: datetime) -> str:
    cn_now = now.astimezone(CN_TZ)
    report_day = cn_now.date()
    if cn_now.time() < time(8, 0):
        report_day -= timedelta(days=1)
    return report_day.isoformat()


def _worker_base_url() -> str:
    return os.environ.get("ACCOUNT_WORKER_URL", "").strip() or DEFAULT_ACCOUNT_WORKER_URL


def _fetch_worker_json(path: str) -> tuple[dict[str, Any] | None, str]:
    base = _worker_base_url().rstrip("/")
    if not base:
        return None, "Worker URL未配置"
    try:
        req = urllib.request.Request(
            f"{base}{path}",
            headers={"User-Agent": "btc-daily-report/1.0", "Cache-Control": "no-cache"},
        )
        with urllib.request.urlopen(req, timeout=18) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("ok"):
            return payload, "正常"
        return None, f"Worker返回异常：{str(payload)[:80]}"
    except Exception as exc:  # noqa: BLE001
        return None, f"Worker读取失败：{exc}"


def _position_note(position: PositionConfig, indicators: Indicators, account: dict[str, Any] | None) -> str:
    if account:
        equity_cny = account.get("equityCny")
        live_position = account.get("position") or {}
        side = live_position.get("side")
        qty = live_position.get("quantityBtc")
        leverage = live_position.get("leverage")
        upl = live_position.get("uplUsdt")
        side_text = "多单" if side == "long" else "空单" if side == "short" else "无仓"
        if side:
            return f"真实账户：权益约 ¥{float(equity_cny or 0):,.0f}｜{qty:g} BTC {side_text}｜{leverage:g}x｜浮盈亏 {float(upl or 0):+,.2f} USDT"
        return f"真实账户：权益约 ¥{float(equity_cny or 0):,.0f}｜当前无BTC永续主仓位"

    has_long = position.long.quantity_btc > 0
    has_short = position.short.quantity_btc > 0
    if has_long:
        pnl = (indicators.latest_price - position.long.entry_price) * position.long.quantity_btc
        return f"真实账户：多单 {position.long.quantity_btc:g} BTC｜{position.long.leverage:g}x｜模板估算浮盈亏 {pnl:+,.2f} USDT"
    if has_short:
        pnl = (position.short.entry_price - indicators.latest_price) * position.short.quantity_btc
        return f"真实账户：空单 {position.short.quantity_btc:g} BTC｜{position.short.leverage:g}x｜模板估算浮盈亏 {pnl:+,.2f} USDT"
    return "真实账户：模板未识别到BTC永续持仓，打开网页后会用实时接口校准。"


def _macro_focus(macro_brief: MacroBrief, macro_payload: dict[str, Any] | None) -> tuple[str, str]:
    upcoming = []
    recent = []
    if macro_payload:
        upcoming = [x for x in macro_payload.get("upcomingEvents", []) if not x.get("placeholder")]
        recent = [x for x in macro_payload.get("recentReleasedEvents", []) if not x.get("placeholder")]

    if upcoming:
        first = next((x for x in upcoming if x.get("status") != "观察" and x.get("impact") in {"高", "中高"}), upcoming[0])
        focus = f"{first.get('title', '宏观事件')}｜{first.get('impact', '-') }影响｜{first.get('status', '-')}"
        judgment = first.get("btcDirection") or "待公布，公布前后优先控制杠杆。"
    elif macro_brief.events:
        first_event = macro_brief.events[0]
        focus = f"{first_event.title}｜{first_event.impact}影响"
        judgment = first_event.btc_direction or first_event.btc_view
    else:
        focus = "未来7天暂无已接入高影响宏观事件"
        judgment = "宏观窗口暂不提供明确方向，优先看技术面和资金费率。"

    if recent:
        last = recent[0]
        focus += f"；已公布：{last.get('title', '-')}"
        judgment = last.get("btcDirection") or judgment
    return focus, judgment


def _sim_note(sim_payload: dict[str, Any] | None) -> str:
    if not sim_payload:
        return "AI模拟盘：日报生成时未读取到模拟盘，网页打开后实时刷新。"
    equity = float(sim_payload.get("equityCny") or 0)
    position = sim_payload.get("position")
    regime = (sim_payload.get("marketRegime") or {}).get("label") or "-"
    decision = sim_payload.get("decision") or "等待"
    if position:
        side = "持多" if position.get("side") == "long" else "持空"
        qty = float(position.get("quantityBtc") or 0)
        return f"AI模拟盘：权益 ¥{equity:,.0f}｜{side} {qty:.4f} BTC｜{regime}｜{decision}"
    return f"AI模拟盘：权益 ¥{equity:,.0f}｜空仓｜{regime}｜{decision}"


def _verdict(indicators: Indicators, advice: Advice, macro_judgment: str) -> str:
    if "利空" in macro_judgment and advice.short_score >= advice.long_score:
        return "偏空震荡，宏观公布前不追单"
    if "利多" in macro_judgment and advice.long_score > advice.short_score:
        return "偏多观察，等待突破确认"
    if advice.risk_score >= 75 or indicators.risk_level == "高":
        return "高风险观望，先控仓位"
    if advice.short_score - advice.long_score >= 15:
        return "偏空，反弹失败优先看空"
    if advice.long_score - advice.short_score >= 15:
        return "偏多，回踩企稳优先看多"
    return "震荡，等待方向确认"


def build_daily_report(
    generated_at: datetime,
    indicators: Indicators,
    position: PositionConfig,
    advice: Advice,
    macro_brief: MacroBrief,
    daily_dir: Path,
    force: bool = False,
) -> DailyReport:
    report_date = daily_report_date(generated_at)
    daily_dir.mkdir(parents=True, exist_ok=True)
    json_path = daily_dir / f"{report_date}.json"
    if json_path.exists() and not force:
        return DailyReport(**json.loads(json_path.read_text(encoding="utf-8")))

    account_payload, account_status = _fetch_worker_json("/?daily=1")
    macro_payload, macro_status = _fetch_worker_json("/macro?daily=1")
    sim_payload, sim_status = _fetch_worker_json("/sim?daily=1")

    macro_focus, macro_judgment = _macro_focus(macro_brief, macro_payload)
    verdict = _verdict(indicators, advice, macro_judgment)
    source_status = "；".join(
        [
            f"账户{account_status}",
            f"宏观{macro_status}",
            f"模拟盘{sim_status}",
        ]
    )
    report = DailyReport(
        report_date=report_date,
        generated_at=generated_at.astimezone(CN_TZ).strftime("%Y-%m-%d %H:%M 北京时间"),
        title="加密日报",
        verdict=verdict,
        btc_price=f"BTC 标记价 {fmt_price(indicators.latest_price)} USDT",
        key_levels=f"压力 {fmt_price(indicators.resistance)}｜支撑 {fmt_price(indicators.support)}｜失守 {fmt_price(indicators.support - max(indicators.atr_15m, indicators.latest_price * 0.004))}",
        strategy=f"策略：{advice.trade_mode}；多头{advice.long_score} / 空头{advice.short_score} / 风险{advice.risk_score}。{advice.strategy_reason}",
        account_note=_position_note(position, indicators, account_payload),
        macro_focus=f"宏观重点：{macro_focus}",
        macro_judgment=f"宏观判断：{macro_judgment}",
        sim_note=_sim_note(sim_payload),
        risk_note=f"风险提示：日报为每日08:00框架，盘中以实时行情、账户和宏观模块校准。数据源：{source_status}",
        archive_name=f"{report_date}.html",
        source_status=source_status,
    )
    json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def render_daily_card(report: DailyReport, recent_reports: list[DailyReport] | None = None) -> str:
    links = "".join(
        f'<a href="daily/{html.escape(item.archive_name)}">{html.escape(item.report_date)}</a>'
        for item in (recent_reports or [])[:7]
    )
    return f"""
    <section class="daily-report" id="dailyReport">
      <div class="daily-head">
        <div>
          <h2>{html.escape(report.title)}</h2>
          <div class="daily-time" id="dailyReportTime">{html.escape(report.generated_at)}</div>
        </div>
        <span class="daily-badge" id="dailyReportBadge">每日08:00</span>
      </div>
      <div class="daily-verdict" id="dailyVerdict">{html.escape(report.verdict)}</div>
      <div class="daily-price-row">
        <div class="daily-price" id="dailyBtcPrice">{html.escape(report.btc_price)}</div>
        <div class="daily-levels" id="dailyKeyLevels">{html.escape(report.key_levels)}</div>
      </div>
      <div class="daily-list">
        <div><strong>今日策略</strong><p id="dailyStrategy">{html.escape(report.strategy)}</p></div>
        <div><strong>真实账户</strong><p id="dailyAccount">{html.escape(report.account_note)}</p></div>
        <div><strong>宏观重点</strong><p id="dailyMacroFocus">{html.escape(report.macro_focus)}</p></div>
        <div><strong>宏观判断</strong><p id="dailyMacroJudgment">{html.escape(report.macro_judgment)}</p></div>
        <div><strong>AI模拟盘</strong><p id="dailySim">{html.escape(report.sim_note)}</p></div>
        <div><strong>风险提示</strong><p id="dailyRisk">{html.escape(report.risk_note)}</p></div>
      </div>
      <div class="daily-links" id="dailyReportLinks">{links or '<span>历史日报生成后显示最近7份。</span>'}</div>
    </section>
    """


def render_daily_page(report: DailyReport, recent_reports: list[DailyReport] | None = None) -> str:
    card = render_daily_card(report, recent_reports)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(report.title)} · {html.escape(report.report_date)}</title>
  <style>
    body {{ margin:0; background:#0b1220; color:#f8fafc; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; line-height:1.55; }}
    main {{ width:min(760px,100%); margin:0 auto; padding:14px; }}
    a {{ color:#93c5fd; }}
    .daily-report {{ background:#111827; border:1px solid #334155; border-radius:12px; padding:16px; }}
    .daily-head {{ display:flex; justify-content:space-between; gap:12px; align-items:start; }}
    h2 {{ margin:0; font-size:34px; line-height:1.05; }}
    .daily-time,.daily-levels,.daily-list p,.daily-links {{ color:#cbd5e1; }}
    .daily-badge {{ border:1px solid #475569; border-radius:999px; padding:4px 10px; color:#fde68a; white-space:nowrap; }}
    .daily-verdict {{ margin:14px 0; padding:14px; border:1px solid #7f1d1d; border-radius:10px; color:#fecaca; font-size:24px; font-weight:800; background:#2a1218; }}
    .daily-price {{ font-size:28px; font-weight:850; color:#6ee7b7; }}
    .daily-list {{ display:grid; gap:10px; margin-top:14px; }}
    .daily-list div {{ border-top:1px solid #334155; padding-top:10px; }}
    .daily-list p {{ margin:4px 0 0; }}
    .daily-links {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; }}
  </style>
</head>
<body><main>{card}</main></body></html>"""


def load_recent_daily_reports(daily_dir: Path, limit: int = 7) -> list[DailyReport]:
    if not daily_dir.exists():
        return []
    reports: list[DailyReport] = []
    for path in sorted(daily_dir.glob("*.json"), reverse=True):
        try:
            reports.append(DailyReport(**json.loads(path.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001
            continue
        if len(reports) >= limit:
            break
    return reports
