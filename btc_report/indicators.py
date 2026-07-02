from __future__ import annotations

import statistics
from dataclasses import dataclass

from .binance import MarketData


@dataclass(frozen=True)
class Indicators:
    latest_price: float
    change_15m_pct: float
    change_1h_pct: float
    change_4h_pct: float
    change_24h_pct: float
    high_24h: float
    low_24h: float
    volatility_24h_pct: float
    volume_4h_ratio: float
    funding_rate_pct: float
    avg_funding_rate_pct: float
    open_interest: float | None
    basis_pct: float | None
    trend: str
    risk_level: str
    support: float
    resistance: float
    warnings: list[str]
    rsi_15m: float = 50.0
    rsi_1h: float = 50.0
    rsi_4h: float = 50.0
    macd_15m: float = 0.0
    macd_signal_15m: float = 0.0
    macd_hist_15m: float = 0.0
    macd_1h: float = 0.0
    macd_signal_1h: float = 0.0
    macd_hist_1h: float = 0.0
    macd_4h: float = 0.0
    macd_signal_4h: float = 0.0
    macd_hist_4h: float = 0.0
    volume_ratio_15m: float = 1.0
    volume_ratio_1h: float = 1.0
    volume_ratio_4h: float = 1.0
    ma_state_15m: str = "均线中性"
    ma_state_1h: str = "均线中性"
    ma_state_4h: str = "均线中性"
    momentum_summary: str = "动能中性"


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a / b - 1.0) * 100.0


def sma(values: list[float], length: int) -> float:
    if not values:
        return 0.0
    chunk = values[-length:]
    return sum(chunk) / len(chunk)


def ema_series(values: list[float], length: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (length + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def rsi(values: list[float], length: int = 14) -> float:
    if len(values) <= length:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for prev, current in zip(values[-length - 1 : -1], values[-length:]):
        change = current - prev
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / length
    avg_loss = sum(losses) / length
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: list[float]) -> tuple[float, float, float]:
    if len(values) < 35:
        return 0.0, 0.0, 0.0
    fast = ema_series(values, 12)
    slow = ema_series(values, 26)
    line = [a - b for a, b in zip(fast, slow)]
    signal = ema_series(line, 9)
    macd_line = line[-1]
    signal_line = signal[-1]
    return macd_line, signal_line, macd_line - signal_line


def volume_ratio(candles: list[dict[str, float]], length: int = 20) -> float:
    if len(candles) < 2:
        return 1.0
    base = sma([c["quote_volume"] for c in candles[:-1]], length)
    return candles[-1]["quote_volume"] / base if base else 1.0


def ma_state(candles: list[dict[str, float]]) -> str:
    if not candles:
        return "均线中性"
    closes = [c["close"] for c in candles]
    latest = closes[-1]
    fast = sma(closes, 6)
    slow = sma(closes, 20)
    if latest > fast > slow:
        return "多头排列"
    if latest < fast < slow:
        return "空头排列"
    return "均线中性"


def momentum_text(rsi_value: float, macd_hist: float, vol_ratio: float, change_pct: float) -> str:
    if rsi_value >= 70:
        rsi_part = "RSI超买"
    elif rsi_value <= 30:
        rsi_part = "RSI超卖"
    elif rsi_value > 55:
        rsi_part = "RSI偏强"
    elif rsi_value < 45:
        rsi_part = "RSI偏弱"
    else:
        rsi_part = "RSI中性"
    macd_part = "MACD红柱扩大" if macd_hist > 0 else "MACD绿柱扩大" if macd_hist < 0 else "MACD中性"
    if vol_ratio > 1.5 and change_pct > 0:
        volume_part = "放量上涨"
    elif vol_ratio > 1.5 and change_pct < 0:
        volume_part = "放量下跌"
    elif vol_ratio < 0.7 and change_pct > 0:
        volume_part = "缩量反弹"
    elif vol_ratio < 0.7 and change_pct < 0:
        volume_part = "缩量下跌"
    else:
        volume_part = "量能普通"
    return f"{rsi_part}，{macd_part}，{volume_part}"


def compute_indicators(data: MarketData) -> Indicators:
    warnings = list(data.data_warnings)
    candles = data.klines_4h
    hourly = data.klines_1h
    scalping = data.klines_15m
    short_candles = scalping or hourly or candles
    if len(candles) < 7:
        warnings.append("4小时K线不足，指标可靠性降低。")
    if not short_candles:
        fallback = data.mark_price or data.index_price or 0.0
        return Indicators(fallback, 0, 0, 0, 0, fallback, fallback, 0, 0, 0, 0, data.open_interest, None, "数据不足", "高", fallback, fallback, warnings)

    closes = [c["close"] for c in candles] if candles else [c["close"] for c in short_candles]
    short_closes = [c["close"] for c in short_candles]
    hourly_closes = [c["close"] for c in hourly] if hourly else short_closes
    latest = data.mark_price or short_closes[-1]
    prev_15m = short_closes[-2] if len(short_closes) >= 2 else short_closes[-1]
    prev_1h = hourly_closes[-2] if len(hourly_closes) >= 2 else short_closes[max(0, len(short_closes) - 5)]
    prev_4h = closes[-2] if len(closes) >= 2 else short_closes[max(0, len(short_closes) - 17)]
    prev_24h = closes[-7] if len(closes) >= 7 else short_closes[0]
    last_24h = scalping[-96:] if len(scalping) >= 96 else hourly[-24:] if len(hourly) >= 24 else candles[-6:] if len(candles) >= 6 else short_candles
    high_24h = max(c["high"] for c in last_24h)
    low_24h = min(c["low"] for c in last_24h)
    vol_base = sma([c["quote_volume"] for c in short_candles[:-1]], 32)
    latest_volume_ratio = short_candles[-1]["quote_volume"] / vol_base if vol_base else 1.0
    returns = [pct(short_closes[i], short_closes[i - 1]) for i in range(1, len(short_closes))]
    volatility = statistics.pstdev(returns[-96:]) if len(returns) >= 2 else 0.0
    funding = data.funding_rates[-1]["rate"] * 100 if data.funding_rates else 0.0
    avg_funding = sum(x["rate"] for x in data.funding_rates[-9:]) / min(len(data.funding_rates), 9) * 100 if data.funding_rates else 0.0
    basis = pct(data.mark_price, data.index_price) if data.mark_price and data.index_price else None
    ma_fast = sma(closes, 6)
    ma_slow = sma(closes, 20)
    change_24h = pct(latest, prev_24h)
    change_4h = pct(latest, prev_4h)
    change_1h = pct(latest, prev_1h)
    change_15m = pct(latest, prev_15m)

    if latest > ma_fast > ma_slow and change_24h > 1.0:
        trend = "上升趋势"
    elif latest < ma_fast < ma_slow and change_24h < -1.0:
        trend = "下降趋势"
    else:
        trend = "震荡/方向不明"

    crowded = abs(funding) > 0.05 or latest_volume_ratio > 1.8 or volatility > 0.9
    if crowded and (abs(change_1h) > 1.2 or abs(change_24h) > 4):
        risk = "高"
    elif crowded or abs(change_1h) > 0.7 or abs(change_24h) > 2:
        risk = "中"
    else:
        risk = "低"

    support_window = scalping[-24:] if len(scalping) >= 24 else hourly[-12:] if hourly else short_candles
    hourly_lows = [c["low"] for c in support_window]
    hourly_highs = [c["high"] for c in support_window]
    closes_15m = [c["close"] for c in scalping] if scalping else short_closes
    closes_1h = [c["close"] for c in hourly] if hourly else short_closes
    closes_4h = [c["close"] for c in candles] if candles else short_closes
    macd_15m, macd_signal_15m, macd_hist_15m = macd(closes_15m)
    macd_1h, macd_signal_1h, macd_hist_1h = macd(closes_1h)
    macd_4h, macd_signal_4h, macd_hist_4h = macd(closes_4h)
    ratio_15m = volume_ratio(scalping or short_candles)
    ratio_1h = volume_ratio(hourly or short_candles)
    ratio_4h = volume_ratio(candles or short_candles)
    rsi_15m = rsi(closes_15m)
    rsi_1h = rsi(closes_1h)
    rsi_4h = rsi(closes_4h)
    return Indicators(
        latest_price=latest,
        change_15m_pct=change_15m,
        change_1h_pct=change_1h,
        change_4h_pct=change_4h,
        change_24h_pct=change_24h,
        high_24h=high_24h,
        low_24h=low_24h,
        volatility_24h_pct=volatility,
        volume_4h_ratio=latest_volume_ratio,
        funding_rate_pct=funding,
        avg_funding_rate_pct=avg_funding,
        open_interest=data.open_interest,
        basis_pct=basis,
        trend=trend,
        risk_level=risk,
        support=min(hourly_lows),
        resistance=max(hourly_highs),
        warnings=warnings,
        rsi_15m=rsi_15m,
        rsi_1h=rsi_1h,
        rsi_4h=rsi_4h,
        macd_15m=macd_15m,
        macd_signal_15m=macd_signal_15m,
        macd_hist_15m=macd_hist_15m,
        macd_1h=macd_1h,
        macd_signal_1h=macd_signal_1h,
        macd_hist_1h=macd_hist_1h,
        macd_4h=macd_4h,
        macd_signal_4h=macd_signal_4h,
        macd_hist_4h=macd_hist_4h,
        volume_ratio_15m=ratio_15m,
        volume_ratio_1h=ratio_1h,
        volume_ratio_4h=ratio_4h,
        ma_state_15m=ma_state(scalping or short_candles),
        ma_state_1h=ma_state(hourly or short_candles),
        ma_state_4h=ma_state(candles or short_candles),
        momentum_summary=f"15m：{momentum_text(rsi_15m, macd_hist_15m, ratio_15m, change_15m)}；1h：{momentum_text(rsi_1h, macd_hist_1h, ratio_1h, change_1h)}；4h：{momentum_text(rsi_4h, macd_hist_4h, ratio_4h, change_4h)}",
    )
