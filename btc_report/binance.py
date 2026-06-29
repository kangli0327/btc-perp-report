from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


BINANCE_BASE_URL = "https://fapi.binance.com"
OKX_BASE_URL = "https://www.okx.com"


@dataclass(frozen=True)
class MarketData:
    symbol: str
    source: str
    klines_15m: list[dict[str, float]]
    klines_4h: list[dict[str, float]]
    klines_1h: list[dict[str, float]]
    funding_rates: list[dict[str, float]]
    open_interest: float | None
    mark_price: float | None
    index_price: float | None
    data_warnings: list[str]


def _get_json(base_url: str, path: str, params: dict[str, Any]) -> Any:
    url = f"{base_url}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "btc-report/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_binance_kline(row: list[Any]) -> dict[str, float]:
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


def _parse_okx_kline(row: list[Any]) -> dict[str, float]:
    ts = float(row[0])
    return {
        "open_time": ts,
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "close_time": ts,
        "quote_volume": float(row[7]) if len(row) > 7 and row[7] else 0.0,
    }


def _fetch_binance(symbol: str) -> MarketData:
    klines_15m_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/klines", {"symbol": symbol, "interval": "15m", "limit": 192})
    klines_4h_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 120})
    klines_1h_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/klines", {"symbol": symbol, "interval": "1h", "limit": 96})
    funding_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 30})
    oi_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/openInterest", {"symbol": symbol})
    premium_raw = _get_json(BINANCE_BASE_URL, "/fapi/v1/premiumIndex", {"symbol": symbol})

    return MarketData(
        symbol=symbol,
        source="Binance USD-M Futures",
        klines_15m=[_parse_binance_kline(row) for row in klines_15m_raw if isinstance(row, list) and len(row) >= 8],
        klines_4h=[_parse_binance_kline(row) for row in klines_4h_raw if isinstance(row, list) and len(row) >= 8],
        klines_1h=[_parse_binance_kline(row) for row in klines_1h_raw if isinstance(row, list) and len(row) >= 8],
        funding_rates=[
            {"time": float(item.get("fundingTime", 0)), "rate": float(item.get("fundingRate", 0))}
            for item in funding_raw
            if isinstance(item, dict)
        ],
        open_interest=float(oi_raw["openInterest"]) if isinstance(oi_raw, dict) and oi_raw.get("openInterest") else None,
        mark_price=float(premium_raw["markPrice"]) if isinstance(premium_raw, dict) and premium_raw.get("markPrice") else None,
        index_price=float(premium_raw["indexPrice"]) if isinstance(premium_raw, dict) and premium_raw.get("indexPrice") else None,
        data_warnings=[],
    )


def _okx_data(path: str, params: dict[str, Any]) -> Any:
    payload = _get_json(OKX_BASE_URL, path, params)
    if not isinstance(payload, dict) or payload.get("code") != "0":
        raise RuntimeError(f"OKX returned {payload}")
    return payload.get("data", [])


def _fetch_okx(symbol: str, prior_warning: str) -> MarketData:
    inst_id = "BTC-USDT-SWAP"
    klines_15m_raw = _okx_data("/api/v5/market/candles", {"instId": inst_id, "bar": "15m", "limit": 192})
    klines_4h_raw = _okx_data("/api/v5/market/candles", {"instId": inst_id, "bar": "4H", "limit": 120})
    klines_1h_raw = _okx_data("/api/v5/market/candles", {"instId": inst_id, "bar": "1H", "limit": 96})
    funding_raw = _okx_data("/api/v5/public/funding-rate", {"instId": inst_id})
    oi_raw = _okx_data("/api/v5/public/open-interest", {"instType": "SWAP", "instId": inst_id})
    mark_raw = _okx_data("/api/v5/public/mark-price", {"instType": "SWAP", "instId": inst_id})
    ticker_raw = _okx_data("/api/v5/market/ticker", {"instId": inst_id})

    klines_15m = [_parse_okx_kline(row) for row in reversed(klines_15m_raw) if isinstance(row, list) and len(row) >= 8]
    klines_4h = [_parse_okx_kline(row) for row in reversed(klines_4h_raw) if isinstance(row, list) and len(row) >= 8]
    klines_1h = [_parse_okx_kline(row) for row in reversed(klines_1h_raw) if isinstance(row, list) and len(row) >= 8]
    funding_rates = [
        {"time": float(item.get("fundingTime", 0)), "rate": float(item.get("fundingRate", 0))}
        for item in funding_raw
        if isinstance(item, dict)
    ]
    mark_price = float(mark_raw[0]["markPx"]) if mark_raw and mark_raw[0].get("markPx") else None
    index_price = float(ticker_raw[0]["idxPx"]) if ticker_raw and ticker_raw[0].get("idxPx") else None
    open_interest = float(oi_raw[0]["oiCcy"]) if oi_raw and oi_raw[0].get("oiCcy") else None

    return MarketData(
        symbol=symbol,
        source="OKX BTC-USDT-SWAP fallback",
        klines_15m=klines_15m,
        klines_4h=klines_4h,
        klines_1h=klines_1h,
        funding_rates=funding_rates,
        open_interest=open_interest,
        mark_price=mark_price,
        index_price=index_price,
        data_warnings=[prior_warning, "Binance 不可用，已自动切换到 OKX BTC-USDT-SWAP 公共数据。"],
    )


def fetch_market_data(symbol: str = "BTCUSDT") -> MarketData:
    try:
        return _fetch_binance(symbol)
    except Exception as exc:  # noqa: BLE001 - report should keep working with fallback data.
        return _fetch_okx(symbol, f"Binance 数据获取失败：{exc}")


def now_ms() -> int:
    return int(time.time() * 1000)
