from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PositionSide:
    quantity_btc: float = 0.0
    entry_price: float = 0.0
    leverage: float = 1.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.quantity_btc * self.entry_price)


@dataclass(frozen=True)
class PositionConfig:
    account_equity_usdt: float
    available_margin_usdt: float
    long: PositionSide
    short: PositionSide
    notes: str = ""
    source_warning: str = ""


@dataclass(frozen=True)
class PreferenceConfig:
    style: str
    max_total_notional_pct: float
    max_single_add_pct: float
    max_drawdown_pct: float
    risk_per_trade_pct: float
    allow_long: bool
    allow_short: bool
    preferred_timeframe: str
    notes: str = ""
    source_warning: str = ""


def _load_json_env(name: str) -> tuple[dict[str, Any], str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}, f"未配置 {name}，已使用保守示例配置。"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"{name} JSON 解析失败：{exc}"
    if not isinstance(data, dict):
        return {}, f"{name} 必须是 JSON object。"
    return data, ""


def _side(data: dict[str, Any]) -> PositionSide:
    return PositionSide(
        quantity_btc=float(data.get("quantity_btc", 0) or 0),
        entry_price=float(data.get("entry_price", 0) or 0),
        leverage=float(data.get("leverage", 1) or 1),
        stop_loss=float(data.get("stop_loss", 0) or 0),
        take_profit=float(data.get("take_profit", 0) or 0),
    )


def load_position() -> PositionConfig:
    data, warning = _load_json_env("POSITION_CONFIG_JSON")
    return PositionConfig(
        account_equity_usdt=float(data.get("account_equity_usdt", 10000) or 10000),
        available_margin_usdt=float(data.get("available_margin_usdt", 0) or 0),
        long=_side(data.get("long", {}) if isinstance(data.get("long", {}), dict) else {}),
        short=_side(data.get("short", {}) if isinstance(data.get("short", {}), dict) else {}),
        notes=str(data.get("notes", "")),
        source_warning=warning,
    )


def load_preference() -> PreferenceConfig:
    data, warning = _load_json_env("PREFERENCE_CONFIG_JSON")
    return PreferenceConfig(
        style=str(data.get("style", "aggressive_trend_following")),
        max_total_notional_pct=float(data.get("max_total_notional_pct", 1.8) or 1.8),
        max_single_add_pct=float(data.get("max_single_add_pct", 0.35) or 0.35),
        max_drawdown_pct=float(data.get("max_drawdown_pct", 0.18) or 0.18),
        risk_per_trade_pct=float(data.get("risk_per_trade_pct", 0.03) or 0.03),
        allow_long=bool(data.get("allow_long", True)),
        allow_short=bool(data.get("allow_short", True)),
        preferred_timeframe=str(data.get("preferred_timeframe", "4h")),
        notes=str(data.get("notes", "")),
        source_warning=warning,
    )

