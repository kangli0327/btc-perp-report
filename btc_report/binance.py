from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


BASE_URL = "https://fapi.binance.com"


@dataclass(frozen=True)
class MarketData:
    symbol: str
    klines_4h: list[dict[str, float]]
    klines_1h: list[dict[str, float]]
    funding_rates: list[dict[str, float]]
    open_interest: float | None
    mark_price: float | None
    index_price: float | None
    data_warnings: list[str]


def _get_json(path: str, params: dict[str, Any]) -> Any:
    url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "btc-report/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _safe(call, warnings: list[str], label: str, fallback):
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - report must degrade instead of failing.
        warnings.append(f"{label} 获取失败：{exc}")
        return fallback


def _parse_kline(row: list[Any]) -> dict[str, float]:
    return {
        "open_time": float(row[0]),
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "close_time": float(row[6]),
        "quote_volume": float(row[7]),
    }


def fetch_market_data(symbol: str = "BTCUSDT") -> MarketData:
    warnings: list[str] = []

    klines_4h_raw = _safe(
        lambda: _get_json("/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 120}),
        warnings,
        "4小时K线",
        [],
    )
    klines_1h_raw = _safe(
        lambda: _get_json("/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 96}),
        warnings,
        "1小时K线",
        [],
    )
    funding_raw = _safe(
        lambda: _get_json("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 30}),
        warnings,
        "资金费率",
        [],
    )
    oi_raw = _safe(
        lambda: _get_json("/fapi/v1/openInterest", {"symbol": symbol}),
        warnings,
        "持仓量",
        {},
    )
    premium_raw = _safe(
        lambda: _get_json("/fapi/v1/premiumIndex", {"symbol": symbol}),
        warnings,
        "标记价格",
        {},
    )

    klines_4h = [_parse_kline(row) for row in klines_4h_raw if isinstance(row, list) and len(row) >= 8]
    klines_1h = [_parse_kline(row) for row in klines_1h_raw if isinstance(row, list) and len(row) >= 8]
    funding_rates = [
        {"time": float(item.get("fundingTime", 0)), "rate": float(item.get("fundingRate", 0))}
        for item in funding_raw
        if isinstance(item, dict)
    ]

    return MarketData(
        symbol=symbol,
        klines_4h=klines_4h,
        klines_1h=klines_1h,
        funding_rates=funding_rates,
        open_interest=float(oi_raw["openInterest"]) if isinstance(oi_raw, dict) and oi_raw.get("openInterest") else None,
        mark_price=float(premium_raw["markPrice"]) if isinstance(premium_raw, dict) and premium_raw.get("markPrice") else None,
        index_price=float(premium_raw["indexPrice"]) if isinstance(premium_raw, dict) and premium_raw.get("indexPrice") else None,
        data_warnings=warnings,
    )


def now_ms() -> int:
    return int(time.time() * 1000)

