from __future__ import annotations

from dataclasses import dataclass

from .config import PositionConfig, PreferenceConfig
from .indicators import Indicators


@dataclass(frozen=True)
class Advice:
    headline: str
    bias: str
    risk_summary: str
    long_plan: str
    short_plan: str
    invalidation: str
    position_summary: str
    action_items: list[str]


def _money(value: float) -> str:
    return f"{value:,.0f} USDT"


def _price(value: float) -> str:
    return f"{value:,.1f}"


def build_advice(position: PositionConfig, pref: PreferenceConfig, ind: Indicators) -> Advice:
    long_notional = position.long.notional
    short_notional = position.short.notional
    total_notional = long_notional + short_notional
    max_notional = position.account_equity_usdt * pref.max_total_notional_pct
    add_budget = max(position.account_equity_usdt * pref.max_single_add_pct, 0)
    usage = total_notional / max_notional if max_notional else 0
    net = long_notional - short_notional

    if ind.trend == "上升趋势":
        bias = "偏多"
    elif ind.trend == "下降趋势":
        bias = "偏空"
    else:
        bias = "观望"

    if ind.risk_level == "高":
        headline = f"{bias}但风险高，优先保护已有仓位"
    elif bias == "偏多":
        headline = "趋势偏多，可等待回踩确认后顺势加多"
    elif bias == "偏空":
        headline = "趋势偏空，可等待反弹受阻后顺势加空"
    else:
        headline = "方向不明，降低追价，等待突破或跌破"

    if usage > 1:
        risk_summary = "当前名义仓位超过偏好上限，任何新增仓位前应先降杠杆或减仓。"
    elif ind.risk_level == "高":
        risk_summary = "波动或拥挤度偏高，新增仓位必须缩小，并以止损优先。"
    else:
        risk_summary = "仓位使用仍有余量，但建议分批执行，避免单点追价。"

    long_plan = "多头："
    short_plan = "空头："
    actions: list[str] = []

    if pref.allow_long:
        if bias == "偏多" and ind.latest_price > ind.support:
            long_plan += f"若价格回踩 {_price(ind.support)} 附近企稳，计划加多不超过 {_money(add_budget)} 名义仓位；止损放在 {_price(ind.support * 0.985)} 下方，第一止盈看 {_price(ind.resistance)}。"
            actions.append("多头回踩企稳时顺势加仓，跌破支撑则停止加仓。")
        elif position.long.quantity_btc > 0:
            long_plan += f"已有多仓继续以 {_price(position.long.stop_loss or ind.support * 0.985)} 作为失效线；若跌破支撑且资金费率仍偏高，减仓 30%-50%。"
            actions.append("已有多仓以支撑/止损线保护利润。")
        else:
            long_plan += "暂不开新多，等待4小时收盘重新站上短期趋势。"
    else:
        long_plan += "偏好禁止做多。"

    if pref.allow_short:
        if bias == "偏空" and ind.latest_price < ind.resistance:
            short_plan += f"若反弹至 {_price(ind.resistance)} 附近受阻，计划加空不超过 {_money(add_budget)} 名义仓位；止损放在 {_price(ind.resistance * 1.015)} 上方，第一止盈看 {_price(ind.support)}。"
            actions.append("空头反弹受阻时顺势加仓，突破阻力则停止加仓。")
        elif position.short.quantity_btc > 0:
            short_plan += f"已有空仓继续以 {_price(position.short.stop_loss or ind.resistance * 1.015)} 作为失效线；若突破阻力且成交放大，减仓 30%-50%。"
            actions.append("已有空仓以阻力/止损线控制反抽风险。")
        else:
            short_plan += "暂不开新空，等待4小时收盘跌破关键支撑。"
    else:
        short_plan += "偏好禁止做空。"

    if ind.risk_level == "高" and total_notional > 0:
        actions.insert(0, "风险等级高：优先检查止损是否有效，暂停扩大双向总仓位。")
    if usage > 0.85:
        actions.insert(0, "仓位接近上限：新增方向前先平掉弱势一侧或降低杠杆。")
    if not actions:
        actions.append("当前没有高质量触发点，等待下一根4小时K线确认。")

    invalidation = f"若4小时收盘跌破 {_price(ind.support)} 且持仓量/成交量同步放大，多头计划失效；若4小时收盘突破 {_price(ind.resistance)}，空头计划失效。"
    position_summary = (
        f"账户权益 {_money(position.account_equity_usdt)}；多头名义 {_money(long_notional)}，"
        f"空头名义 {_money(short_notional)}，净敞口 {_money(net)}，总仓位使用 {usage * 100:.1f}%。"
    )

    return Advice(headline, bias, risk_summary, long_plan, short_plan, invalidation, position_summary, actions)

