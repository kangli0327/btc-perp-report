from __future__ import annotations

import statistics
from dataclasses import dataclass

from .binance import MarketData


@dataclass(frozen=True)
class Indicators:
    latest_price: float
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
    if len(candles) < 7:
        warnings.append("4小时K线不足，指标可靠性降低。")
    if not candles:
        fallback = data.mark_price or data.index_price or 0.0
        return Indicators(fallback, 0, 0, fallback, fallback, 0, 0, 0, 0, data.open_interest, None, "数据不足", "高", fallback, fallback, warnings)

    closes = [c["close"] for c in candles]
    latest = data.mark_price or closes[-1]
    prev_4h = closes[-2] if len(closes) >= 2 else closes[-1]
    prev_24h = closes[-7] if len(closes) >= 7 else closes[0]
    last_24h = candles[-6:] if len(candles) >= 6 else candles
    high_24h = max(c["high"] for c in last_24h)
    low_24h = min(c["low"] for c in last_24h)
    vol_base = sma([c["quote_volume"] for c in candles[:-1]], 20)
    volume_ratio = candles[-1]["quote_volume"] / vol_base if vol_base else 1.0
    returns = [pct(closes[i], closes[i - 1]) for i in range(1, len(closes))]
    volatility = statistics.pstdev(returns[-6:]) if len(returns) >= 2 else 0.0
    funding = data.funding_rates[-1]["rate"] * 100 if data.funding_rates else 0.0
    avg_funding = sum(x["rate"] for x in data.funding_rates[-9:]) / min(len(data.funding_rates), 9) * 100 if data.funding_rates else 0.0
    basis = pct(data.mark_price, data.index_price) if data.mark_price and data.index_price else None
    ma_fast = sma(closes, 6)
    ma_slow = sma(closes, 20)
    change_24h = pct(latest, prev_24h)
    change_4h = pct(latest, prev_4h)

    if latest > ma_fast > ma_slow and change_24h > 1.0:
        trend = "上升趋势"
    elif latest < ma_fast < ma_slow and change_24h < -1.0:
        trend = "下降趋势"
    else:
        trend = "震荡/方向不明"

    crowded = abs(funding) > 0.05 or volume_ratio > 1.8 or volatility > 2.8
    if crowded and abs(change_24h) > 4:
        risk = "高"
    elif crowded or abs(change_24h) > 2:
        risk = "中"
    else:
        risk = "低"

    hourly_lows = [c["low"] for c in hourly[-24:]] if hourly else [low_24h]
    hourly_highs = [c["high"] for c in hourly[-24:]] if hourly else [high_24h]
    return Indicators(
        latest_price=latest,
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

