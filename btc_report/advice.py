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
    long_score: int = 0
    short_score: int = 0
    risk_score: int = 0
    trade_mode: str = "观望"
    strategy_reason: str = ""
    entry_conditions: list[str] | None = None
    strategy_cards: list[tuple[str, str]] | None = None


def _money(value: float) -> str:
    return f"{value:,.0f} USDT"


def _price(value: float) -> str:
    return f"{value:,.1f}"


def _band(center: float, pct: float) -> str:
    return f"{_price(center * (1 - pct))} - {_price(center * (1 + pct))}"


def _clamp_score(value: float) -> int:
    return max(0, min(100, round(value)))


def _strategy_scores(position: PositionConfig, ind: Indicators, liq_gap_pct: float) -> tuple[int, int, int, str, str, list[str]]:
    long_score = 35.0
    short_score = 35.0
    reasons: list[str] = []
    conditions: list[str] = []

    if ind.rsi_4h > 55:
        long_score += 14
        reasons.append(f"4小时RSI {ind.rsi_4h:.1f} 高于55，趋势偏多")
    elif ind.rsi_4h < 45:
        short_score += 14
        reasons.append(f"4小时RSI {ind.rsi_4h:.1f} 低于45，趋势偏空")
    else:
        reasons.append(f"4小时RSI {ind.rsi_4h:.1f} 中性，趋势过滤不强")

    if ind.macd_hist_1h > 0:
        long_score += 16
        reasons.append("1小时MACD红柱为正，动能支持多头")
    elif ind.macd_hist_1h < 0:
        short_score += 16
        reasons.append("1小时MACD绿柱为负，动能支持空头")

    if ind.macd_hist_15m > 0 and ind.volume_ratio_15m > 1.2:
        long_score += 10
        reasons.append("15分钟放量上行，短线多头动能增强")
    elif ind.macd_hist_15m < 0 and ind.volume_ratio_15m > 1.2:
        short_score += 10
        reasons.append("15分钟放量下行，短线空头动能增强")
    elif ind.volume_ratio_15m < 0.8:
        reasons.append("15分钟量能偏低，突破确认度不足")

    if ind.ma_state_4h == "多头排列":
        long_score += 12
        conditions.append("4小时均线多头排列，多单只等回踩或突破确认")
    elif ind.ma_state_4h == "空头排列":
        short_score += 12
        conditions.append("4小时均线空头排列，空单只等反弹受阻或跌破确认")

    if ind.ema_state_4h in {"EMA多头排列", "EMA偏多"}:
        long_score += 12
        reasons.append(f"4小时{ind.ema_state_4h}，大周期更支持顺势做多")
    elif ind.ema_state_4h in {"EMA空头排列", "EMA偏空"}:
        short_score += 12
        reasons.append(f"4小时{ind.ema_state_4h}，大周期更支持顺势做空")

    if ind.price_vs_vwap_pct > 0.25:
        long_score += 5
        reasons.append("价格在日内VWAP上方，日内资金成本对多头更友好")
    elif ind.price_vs_vwap_pct < -0.25:
        short_score += 5
        reasons.append("价格在日内VWAP下方，日内资金成本对空头更友好")

    if ind.funding_rate_pct > 0.02 and ind.change_1h_pct < 0:
        short_score += 8
        reasons.append("资金费率偏正但价格走弱，多头拥挤偏利空")
    elif ind.funding_rate_pct < -0.02 and ind.change_1h_pct > 0:
        long_score += 8
        reasons.append("资金费率偏负但价格走强，空头拥挤偏利多")

    risk_score = 20.0
    if ind.risk_level == "高":
        risk_score += 30
    elif ind.risk_level == "中":
        risk_score += 15
    if ind.atr_15m_pct > 0.6:
        risk_score += 15
        conditions.append("15分钟ATR偏大，止损要按波动放宽，但仓位必须同步缩小")
    elif ind.atr_15m_pct < 0.18:
        conditions.append("15分钟ATR偏小，行情可能横盘，突破前不要提前重仓")
    if position.liquidation_price and liq_gap_pct < 1.2:
        risk_score += 60
    elif position.liquidation_price and liq_gap_pct < 3:
        risk_score += 35
    if abs(long_score - short_score) < 12:
        risk_score += 15
        conditions.append("RSI/MACD多空分歧明显，信号不足时不追单")

    long_final = _clamp_score(long_score)
    short_final = _clamp_score(short_score)
    risk_final = _clamp_score(risk_score)
    if risk_final >= 80:
        mode = "禁止交易"
    elif position.short.quantity_btc > 0 or position.long.quantity_btc > 0:
        mode = "只管理持仓" if abs(long_final - short_final) < 18 else ("只做空" if short_final > long_final else "只做多")
    elif long_final >= 62 and long_final - short_final >= 12:
        mode = "只做多"
    elif short_final >= 62 and short_final - long_final >= 12:
        mode = "只做空"
    elif long_final >= 55 and short_final >= 55:
        mode = "多空都可"
    else:
        mode = "等待确认"

    if not conditions:
        conditions.append("等待15分钟收盘确认，避免在区间中部追单")
    return long_final, short_final, risk_final, mode, "；".join(reasons[:4]), conditions


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


def _macd_words(value: float) -> str:
    if value > 0:
        return "MACD红柱，短线动能偏多"
    if value < 0:
        return "MACD绿柱，短线动能偏空"
    return "MACD接近零轴，动能不明显"


def _rsi_words(value: float) -> str:
    if value >= 70:
        return "RSI进入超买区，追多容易被回落扫到"
    if value <= 30:
        return "RSI进入超卖区，追空容易遇到反弹"
    if value > 55:
        return "RSI偏强，多头有一定主动权"
    if value < 45:
        return "RSI偏弱，空头有一定主动权"
    return "RSI在中间区，方向优势不明显"


def _strategy_cards(ind: Indicators, trade_mode: str, liq_gap_pct: float) -> list[tuple[str, str]]:
    direction = (
        f"4小时{ind.ema_state_4h}，{_rsi_words(ind.rsi_4h)}；这决定了大方向过滤，逆势单只做短线，不适合重仓硬扛。"
    )
    momentum = (
        f"1小时{_macd_words(ind.macd_hist_1h)}，15分钟{_macd_words(ind.macd_hist_15m)}；如果两个周期同向，入场可信度更高，冲突时先等下一根15分钟K线确认。"
    )
    volume = (
        f"15分钟成交量是均量的{ind.volume_ratio_15m:.2f}倍，1小时成交量是均量的{ind.volume_ratio_1h:.2f}倍；{ind.position_context}。"
    )
    location = (
        f"当前支撑约{_price(ind.support)}，阻力约{_price(ind.resistance)}，日内VWAP约{_price(ind.vwap_24h)}；价格相对VWAP {ind.price_vs_vwap_pct:+.2f}%，用来判断是在资金平均成本上方还是下方。"
    )
    volatility = (
        f"15分钟ATR约{_price(ind.atr_15m)} USDT（{ind.atr_15m_pct:.2f}%）；止损不能小于正常波动，若止损太远则必须缩小保证金。"
    )
    funding = (
        f"资金费率{ind.funding_rate_pct:+.3f}%；正费率且价格走弱偏利空，负费率且价格抗跌偏利多，极端费率说明一边太拥挤。"
    )
    risk = (
        f"最终模式：{trade_mode}。100x下优先看止损和强平，距离强平约{liq_gap_pct:.2f}%时，不管指标多漂亮都不能无条件加仓。"
        if liq_gap_pct
        else f"最终模式：{trade_mode}。100x下必须先确定止损，再决定保证金大小。"
    )
    return [
        ("大方向", direction),
        ("短线动能", momentum),
        ("量价关系", volume),
        ("位置判断", location),
        ("波动率", volatility),
        ("资金情绪", funding),
        ("风险结论", risk),
    ]


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
    long_score, short_score, risk_score, trade_mode, strategy_reason, entry_conditions = _strategy_scores(position, ind, liq_gap_pct)

    if position.liquidation_price and liq_gap_pct < 1.2:
        headline = "强平距离过近，先处理风控，再考虑方向"
    elif trade_mode == "只做空":
        headline = "多周期动能偏空，空单按反弹受阻或跌破确认执行"
    elif trade_mode == "只做多":
        headline = "多周期动能偏多，空单不宜硬扛突破"
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
    long_trigger = max(ind.resistance, ind.latest_price * 1.002)
    long_stop = _nearest_stop_for_long(position, ind)
    long_tp1 = long_trigger * 1.006
    long_tp2 = long_trigger * 1.014
    short_entry = ind.resistance
    short_stop = _nearest_stop_for_short(position, ind)
    active_short_entry = position.short.entry_price if has_short and position.short.entry_price else ind.latest_price
    short_tp1 = min(active_short_entry, ind.latest_price * 0.992, (ind.support + ind.resistance) / 2)
    short_tp2 = min(ind.support, short_tp1 * 0.992)

    if pref.allow_long:
        long_gate = "允许" if trade_mode in {"只做多", "多空都可"} else "等待评分确认"
        long_plan = (
            f"多头计划（{long_gate}）：只有在15分钟收盘站上 {_price(ind.resistance)}，或回踩 {_band(long_entry, 0.002)} "
            f"后重新放量上行，才考虑做多；单次新增名义仓位不超过 {_money(add_budget)}。"
            f"止损 {_price(long_stop)}，止盈分两档：{_price(long_tp1)} / {_price(long_tp2)}。"
        )
    else:
        long_plan = "多头计划：偏好禁止做多。"

    if pref.allow_short:
        short_gate = "允许" if trade_mode in {"只做空", "多空都可", "只管理持仓"} else "等待评分确认"
        if has_short:
            emergency_stop = position.short.stop_loss or short_stop
            short_plan = (
                f"空头计划（{short_gate}）：已有空单 {position.short.quantity_btc:g} BTC，开仓均价 {_price(position.short.entry_price)}。"
                f"若价格反弹到 {_band(short_entry, 0.002)} 受阻，可继续持有；不建议在强平价附近继续加空。"
                f"必须设置硬止损 {_price(emergency_stop)}，第一止盈 {_price(short_tp1)}，第二止盈 {_price(short_tp2)}。"
                f"若跌破 {_price(short_tp1)} 后反抽不破，可把止损下移到开仓价 {_price(position.short.entry_price)} 附近。"
            )
            actions.append(f"立即补一个空单硬止损：{_price(emergency_stop)}，避免接近强平价 {_price(position.liquidation_price)}。")
            actions.append(f"第一减仓/止盈观察：{_price(short_tp1)}；若成交放大跌破，再看 {_price(short_tp2)}。")
        else:
            short_plan = (
                f"空头计划（{short_gate}）：只有反弹到 {_band(short_entry, 0.002)} 受阻，或15分钟收盘跌破 {_price(ind.support)}，才考虑开空；"
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
        f"空头失效：15分钟收盘突破 {_price(ind.resistance)} 或触发止损 {_price(short_stop)}；"
        f"多头失效：15分钟收盘跌破 {_price(ind.support)} 或触发止损 {_price(long_stop)}。"
    )
    position_summary = (
        f"账户权益 {_money(position.account_equity_usdt)}；可用保证金 {_money(position.available_margin_usdt)}；"
        f"多头名义 {_money(long_notional)}，空头名义 {_money(short_notional)}，净敞口 {_money(net)}，"
        f"总仓位使用 {usage * 100:.1f}%。"
    )

    return Advice(
        headline,
        bias,
        risk_summary,
        long_plan,
        short_plan,
        invalidation,
        position_summary,
        actions,
        long_score=long_score,
        short_score=short_score,
        risk_score=risk_score,
        trade_mode=trade_mode,
        strategy_reason=strategy_reason,
        entry_conditions=entry_conditions,
        strategy_cards=_strategy_cards(ind, trade_mode, liq_gap_pct),
    )
