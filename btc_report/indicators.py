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


def pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a / b - 1.0) * 100.0


def sma(values: list[float], length: int) -> float:
    if not values:
        return 0.0
    chunk = values[-length:]
    return sum(chunk) / len(chunk)


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
    volume_ratio = short_candles[-1]["quote_volume"] / vol_base if vol_base else 1.0
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

    crowded = abs(funding) > 0.05 or volume_ratio > 1.8 or volatility > 0.9
    if crowded and (abs(change_1h) > 1.2 or abs(change_24h) > 4):
        risk = "高"
    elif crowded or abs(change_1h) > 0.7 or abs(change_24h) > 2:
        risk = "中"
    else:
        risk = "低"

    support_window = scalping[-24:] if len(scalping) >= 24 else hourly[-12:] if hourly else short_candles
    hourly_lows = [c["low"] for c in support_window]
    hourly_highs = [c["high"] for c in support_window]
    return Indicators(
        latest_price=latest,
        change_15m_pct=change_15m,
        change_1h_pct=change_1h,
        change_4h_pct=change_4h,
        change_24h_pct=change_24h,
        high_24h=high_24h,
        low_24h=low_24h,
        volatility_24h_pct=volatility,
        volume_4h_ratio=volume_ratio,
        funding_rate_pct=funding,
        avg_funding_rate_pct=avg_funding,
        open_interest=data.open_interest,
        basis_pct=basis,
        trend=trend,
        risk_level=risk,
        support=min(hourly_lows),
        resistance=max(hourly_highs),
        warnings=warnings,
    )
