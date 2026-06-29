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


def _band(center: float, pct: float) -> str:
    return f"{_price(center * (1 - pct))} - {_price(center * (1 + pct))}"


def _nearest_stop_for_short(position: PositionConfig, ind: Indicators) -> float:
    candidates = [ind.resistance * 1.003, ind.latest_price * 1.006]
    if position.liquidation_price:
        candidates.append(position.liquidation_price * 0.997)
    return min(c for c in candidates if c > ind.latest_price)


def _nearest_stop_for_long(position: PositionConfig, ind: Indicators) -> float:
    candidates = [ind.support * 0.997, ind.latest_price * 0.994]
    if position.liquidation_price:
        candidates.append(position.liquidation_price * 1.003)
    return max(c for c in candidates if c < ind.latest_price)


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

    has_short = position.short.quantity_btc > 0
    has_long = position.long.quantity_btc > 0
    liq_gap_pct = 0.0
    if position.liquidation_price and has_short:
        liq_gap_pct = (position.liquidation_price / ind.latest_price - 1) * 100
    elif position.liquidation_price and has_long:
        liq_gap_pct = (1 - position.liquidation_price / ind.latest_price) * 100

    if position.liquidation_price and liq_gap_pct < 1.2:
        headline = "强平距离过近，先处理风控，再考虑方向"
    elif ind.risk_level == "高":
        headline = f"{bias}但波动偏高，优先保护已有仓位"
    elif bias == "偏多":
        headline = "趋势偏多，空单不宜扛突破，多单等待回踩"
    elif bias == "偏空":
        headline = "趋势偏空，空单可持有但必须设置止损"
    else:
        headline = "方向不明，以区间和强平保护为核心"

    if position.liquidation_price and liq_gap_pct < 1.2:
        risk_summary = f"当前强平价 {_price(position.liquidation_price)}，距离现价约 {liq_gap_pct:.2f}%，100倍仓位容错很低，必须先设置硬止损。"
    elif usage > 1:
        risk_summary = "当前名义仓位超过偏好上限，新增仓位前应先降杠杆或减仓。"
    elif ind.risk_level == "高":
        risk_summary = "波动或拥挤度偏高，新增仓位必须缩小，并以止损优先。"
    else:
        risk_summary = "仓位仍有余量，但建议只在明确触发位分批执行。"

    actions: list[str] = []
    long_entry = ind.support
    long_stop = _nearest_stop_for_long(position, ind)
    long_tp1 = max(ind.latest_price * 1.012, (ind.support + ind.resistance) / 2)
    long_tp2 = ind.resistance
    short_entry = ind.resistance
    short_stop = _nearest_stop_for_short(position, ind)
    short_tp1 = min(ind.latest_price * 0.988, (ind.support + ind.resistance) / 2)
    short_tp2 = ind.support

    if pref.allow_long:
        long_plan = (
            f"多头计划：只有在4小时收盘站上 {_price(ind.resistance)}，或回踩 {_band(long_entry, 0.002)} "
            f"后重新放量上行，才考虑做多；单次新增名义仓位不超过 {_money(add_budget)}。"
            f"止损 {_price(long_stop)}，止盈分两档：{_price(long_tp1)} / {_price(long_tp2)}。"
        )
    else:
        long_plan = "多头计划：偏好禁止做多。"

    if pref.allow_short:
        if has_short:
            emergency_stop = position.short.stop_loss or short_stop
            short_plan = (
                f"空头计划：已有空单 0.1 BTC，开仓均价 {_price(position.short.entry_price)}。"
                f"若价格反弹到 {_band(short_entry, 0.002)} 受阻，可继续持有；不建议在强平价附近继续加空。"
                f"必须设置硬止损 {_price(emergency_stop)}，第一止盈 {_price(short_tp1)}，第二止盈 {_price(short_tp2)}。"
                f"若跌破 {_price(short_tp1)} 后反抽不破，可把止损下移到开仓价 {_price(position.short.entry_price)} 附近。"
            )
            actions.append(f"立即补一个空单硬止损：{_price(emergency_stop)}，避免接近强平价 {_price(position.liquidation_price)}。")
            actions.append(f"第一减仓/止盈观察：{_price(short_tp1)}；若成交放大跌破，再看 {_price(short_tp2)}。")
        else:
            short_plan = (
                f"空头计划：只有反弹到 {_band(short_entry, 0.002)} 受阻，或4小时收盘跌破 {_price(ind.support)}，才考虑开空；"
                f"单次新增名义仓位不超过 {_money(add_budget)}。止损 {_price(short_stop)}，止盈 { _price(short_tp1)} / {_price(short_tp2)}。"
            )
    else:
        short_plan = "空头计划：偏好禁止做空。"

    if position.liquidation_price and liq_gap_pct < 1.2:
        actions.insert(0, "当前最重要动作不是加仓，而是设置止损或降低杠杆。")
    if ind.risk_level == "高" and total_notional > 0:
        actions.append("风险等级高：暂停扩大总仓位，先保护现有仓位。")
    if usage > 0.85:
        actions.append("仓位接近上限：新增方向前先减掉弱势一侧或降低杠杆。")
    if not actions:
        actions.append("当前没有高质量触发点，等待下一根4小时K线确认。")

    invalidation = (
        f"空头失效：4小时收盘突破 {_price(ind.resistance)} 或触发止损 {_price(short_stop)}；"
        f"多头失效：4小时收盘跌破 {_price(ind.support)} 或触发止损 {_price(long_stop)}。"
    )
    position_summary = (
        f"账户权益 {_money(position.account_equity_usdt)}；可用保证金 {_money(position.available_margin_usdt)}；"
        f"多头名义 {_money(long_notional)}，空头名义 {_money(short_notional)}，净敞口 {_money(net)}，"
        f"总仓位使用 {usage * 100:.1f}%。"
    )

    return Advice(headline, bias, risk_summary, long_plan, short_plan, invalidation, position_summary, actions)
