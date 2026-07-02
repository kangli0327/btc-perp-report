from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import PositionConfig, PositionSide


OKX_BASE_URL = "https://www.okx.com"
INST_ID = "BTC-USDT-SWAP"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _credentials() -> tuple[str, str, str] | None:
    key = os.environ.get("OKX_API_KEY", "").strip()
    secret = os.environ.get("OKX_API_SECRET", "").strip()
    passphrase = os.environ.get("OKX_API_PASSPHRASE", "").strip()
    if not key or not secret or not passphrase:
        return None
    return key, secret, passphrase


def _sign(secret: str, timestamp: str, method: str, request_path: str, body: str = "") -> str:
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _private_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    creds = _credentials()
    if creds is None:
        raise RuntimeError("未配置 OKX 私有API Secrets")
    key, secret, passphrase = creds
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request_path = f"{path}{query}"
    timestamp = _timestamp()
    req = urllib.request.Request(
        f"{OKX_BASE_URL}{request_path}",
        headers={
            "OK-ACCESS-KEY": key,
            "OK-ACCESS-SIGN": _sign(secret, timestamp, "GET", request_path),
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Accept": "application/json",
            "User-Agent": "btc-report/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("code") != "0":
        code = payload.get("code") if isinstance(payload, dict) else "unknown"
        msg = payload.get("msg") if isinstance(payload, dict) else "unknown"
        raise RuntimeError(f"OKX私有接口返回异常：{code} {msg}")
    return payload


def _public_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    req = urllib.request.Request(f"{OKX_BASE_URL}{path}{query}", headers={"User-Agent": "btc-report/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("code") != "0":
        raise RuntimeError("OKX公开合约规格接口返回异常")
    return payload


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _balance_numbers(balance: dict[str, Any]) -> tuple[float, float]:
    rows = balance.get("data") or []
    if not rows:
        return 0.0, 0.0
    account = rows[0]
    total_equity = _float(account.get("totalEq") or account.get("adjEq"))
    available = 0.0
    for detail in account.get("details") or []:
        if detail.get("ccy") == "USDT":
            available = _float(detail.get("availBal") or detail.get("availEq") or detail.get("cashBal"))
            if not total_equity:
                total_equity = _float(detail.get("eq"))
            break
    return total_equity, available


def _contract_size() -> float:
    payload = _public_get("/api/v5/public/instruments", {"instType": "SWAP", "instId": INST_ID})
    rows = payload.get("data") or []
    if not rows:
        return 1.0
    contract_value = _float(rows[0].get("ctVal"))
    return contract_value or 1.0


def _position_side(row: dict[str, Any], contract_size: float) -> PositionSide:
    return PositionSide(
        quantity_btc=abs(_float(row.get("pos"))) * contract_size,
        entry_price=_float(row.get("avgPx")),
        leverage=_float(row.get("lever")) or 1.0,
    )


def _position_margin(row: dict[str, Any], leverage: float) -> float:
    margin = _float(row.get("margin"))
    if margin:
        return margin
    imr = _float(row.get("imr"))
    if imr:
        return imr
    notional = _float(row.get("notionalUsd"))
    return notional / max(leverage, 1.0) if notional else 0.0


def fetch_okx_position() -> PositionConfig:
    balance = _private_get("/api/v5/account/balance", {"ccy": "USDT"})
    positions = _private_get("/api/v5/account/positions", {"instType": "SWAP", "instId": INST_ID})
    contract_size = _contract_size()
    account_equity, available_margin = _balance_numbers(balance)
    long = PositionSide()
    short = PositionSide()
    liquidation_price = 0.0
    initial_margin = 0.0
    for row in positions.get("data") or []:
        if row.get("instId") != INST_ID or _float(row.get("pos")) == 0:
            continue
        side_name = str(row.get("posSide") or "").lower()
        side = _position_side(row, contract_size)
        if side_name == "long":
            long = side
        elif side_name == "short":
            short = side
        elif _float(row.get("pos")) > 0:
            long = side
        else:
            short = side
        liquidation_price = _float(row.get("liqPx")) or liquidation_price
        initial_margin += _position_margin(row, side.leverage)
    return PositionConfig(
        account_equity_usdt=account_equity,
        available_margin_usdt=available_margin,
        long=long,
        short=short,
        liquidation_price=liquidation_price,
        initial_margin_usdt=initial_margin,
        notes="OKX私有只读API自动同步",
        source_warning="仓位来源：OKX私有只读API。网页会公开展示同步后的仓位和盈亏。",
    )
