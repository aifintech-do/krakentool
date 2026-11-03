# krakentool — Kraken Spot WebSocket API v2 market-data consumer.
# Copyright (C) 2026 aifintech-do
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Build and parse Kraken Spot WebSocket API v2 market-data messages.

Public endpoint: wss://ws.kraken.com/v2
Channels: ticker, trade, book, ohlc.
Level 3 (individual orders) is authenticated and uses wss://ws-l3.kraken.com/v2.
Crypto and forex share each socket; subscribe with v2 symbols (`BTC/USD`, `EUR/USD`).
"""

from __future__ import annotations

from typing import Any, Iterable

from krakentool.assets import asset_class, parse_symbol

PUBLIC_WS_URL = "wss://ws.kraken.com/v2"
AUTH_WS_URL = "wss://ws-auth.kraken.com/v2"
L3_WS_URL = "wss://ws-l3.kraken.com/v2"
REST_URL = "https://api.kraken.com"

MARKET_CHANNELS = ("ticker", "trade", "book", "ohlc", "level3")
BOOK_DEPTHS = (10, 25, 100, 500, 1000)
L3_DEPTHS = (10, 100, 1000)
OHLC_INTERVALS = (1, 5, 15, 30, 60, 240, 1440, 10080, 21600)
EVENT_TRIGGERS = ("bbo", "trades")

# One subscribe frame stays small. Kraken acks each symbol separately.
SYMBOL_CHUNK = 50


def normalize_symbols(symbols: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in symbols:
        for piece in raw.split(","):
            piece = piece.strip()
            if not piece:
                continue
            symbol = "/".join(parse_symbol(piece))
            if symbol not in seen:
                seen.add(symbol)
                ordered.append(symbol)
    if not ordered:
        raise ValueError("at least one symbol is required")
    return ordered


def build_subscriptions(
    symbols: list[str],
    channels: list[str],
    *,
    snapshot: bool = True,
    event_trigger: str = "bbo",
    book_depth: int = 10,
    l3_depth: int = 10,
    ohlc_interval: int = 1,
    token: str | None = None,
    chunk_size: int = SYMBOL_CHUNK,
    req_id_start: int = 1,
) -> list[dict[str, Any]]:
    """Return subscribe frames. `req_id` increases by one per frame.

    `token` is required when `level3` is included. It is placed only in the
    subscribe params and must not be logged.
    """
    if event_trigger not in EVENT_TRIGGERS:
        raise ValueError(f"event_trigger must be one of {EVENT_TRIGGERS}")
    if book_depth not in BOOK_DEPTHS:
        raise ValueError(f"book depth must be one of {BOOK_DEPTHS}")
    if "level3" in channels and l3_depth not in L3_DEPTHS:
        raise ValueError(f"level3 depth must be one of {L3_DEPTHS}")
    if "level3" in channels and not token:
        raise ValueError("level3 requires an authentication token")
    if ohlc_interval not in OHLC_INTERVALS:
        raise ValueError(f"ohlc interval must be one of {OHLC_INTERVALS}")
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")

    unknown = [name for name in channels if name not in MARKET_CHANNELS]
    if unknown:
        raise ValueError(
            f"unknown channel(s) {unknown}; expected {', '.join(MARKET_CHANNELS)}"
        )
    if not channels:
        raise ValueError("at least one channel is required")

    frames: list[dict[str, Any]] = []
    req_id = req_id_start
    for channel in channels:
        for start in range(0, len(symbols), chunk_size):
            chunk = symbols[start : start + chunk_size]
            params: dict[str, Any] = {
                "channel": channel,
                "symbol": chunk,
                "snapshot": snapshot,
            }
            if channel == "ticker":
                params["event_trigger"] = event_trigger
            elif channel == "book":
                params["depth"] = book_depth
            elif channel == "level3":
                params["depth"] = l3_depth
                params["token"] = token
            elif channel == "ohlc":
                params["interval"] = ohlc_interval
            frames.append({"method": "subscribe", "params": params, "req_id": req_id})
            req_id += 1
    return frames


def ping(req_id: int) -> dict[str, Any]:
    if req_id <= 0:
        raise ValueError("req_id must be > 0")
    return {"method": "ping", "req_id": req_id}


def market_events(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize a ticker/trade/book/level3/ohlc snapshot or update.

    Non-market frames (heartbeat, status, subscribe acks, pong) yield nothing.
    Each event keeps the venue fields and adds channel, type, and asset_class.
    """
    channel = message.get("channel")
    if channel not in MARKET_CHANNELS:
        return []
    data = message.get("data")
    if not isinstance(data, list):
        return []

    events: list[dict[str, Any]] = []
    msg_type = message.get("type")
    for item in data:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        event = dict(item)
        event["channel"] = channel
        event["type"] = msg_type
        if isinstance(symbol, str):
            event["asset_class"] = asset_class(symbol)
        else:
            event["asset_class"] = "unknown"
        events.append(event)
    return events


def control_summary(message: dict[str, Any]) -> dict[str, Any] | None:
    """Compact view of connection and subscription frames, or None for market data."""
    method = message.get("method")
    if method in {"subscribe", "unsubscribe", "pong", "ping"}:
        result = message.get("result")
        result = result if isinstance(result, dict) else {}
        return {
            "kind": method,
            "success": message.get("success"),
            "error": message.get("error"),
            "req_id": message.get("req_id"),
            "channel": result.get("channel"),
            "symbol": result.get("symbol"),
            "time_out": message.get("time_out"),
        }
    channel = message.get("channel")
    if channel == "heartbeat":
        return {"kind": "heartbeat"}
    if channel == "status":
        data = message.get("data")
        first = data[0] if isinstance(data, list) and data else {}
        if not isinstance(first, dict):
            first = {}
        return {
            "kind": "status",
            "system": first.get("system"),
            "api_version": first.get("api_version"),
            "version": first.get("version"),
            "connection_id": first.get("connection_id"),
        }
    return None
