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

"""Own trades and orders over the authenticated Spot WebSocket v2 executions channel.

`wss://ws-auth.kraken.com/v2` sends a snapshot of open orders and the latest
50 fills, then live order and fill events. Closed orders older than that
snapshot are not replayed. Symbols arrive already in v2 form (`BTC/USD`).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import websockets

from krakentool.assets import asset_class
from krakentool.credentials import CredentialsError, fetch_websocket_token, load_credentials
from krakentool.protocol import AUTH_WS_URL

Emit = Callable[[dict[str, Any]], None]

# Longest first so ZUSD wins over USD and USDT wins over USD.
_QUOTES = (
    "USDT",
    "USDC",
    "PYUSD",
    "ZUSD",
    "ZEUR",
    "ZGBP",
    "ZJPY",
    "ZCAD",
    "ZAUD",
    "ZCHF",
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CAD",
    "AUD",
    "CHF",
    "DAI",
    "BTC",
)
_ASSETS = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "XLTC": "LTC",
    "XXRP": "XRP",
    "XXLM": "XLM",
    "XXMR": "XMR",
    "XZEC": "ZEC",
    "XETC": "ETC",
    "XMLN": "MLN",
    "XREP": "REP",
    "XXDG": "XDG",
    "XDG": "XDG",
    "ZUSD": "USD",
    "ZEUR": "EUR",
    "ZGBP": "GBP",
    "ZJPY": "JPY",
    "ZCAD": "CAD",
    "ZAUD": "AUD",
    "ZCHF": "CHF",
}


class HistoryError(RuntimeError):
    """The executions stream failed."""


def to_v2_symbol(pair: str) -> str:
    """Map a REST pair name or an already-slashed symbol to `BASE/QUOTE`."""
    text = pair.strip().upper()
    if not text:
        raise ValueError("empty pair")
    if "/" in text:
        base, quote = text.split("/", 1)
        return f"{_ASSETS.get(base, base)}/{_ASSETS.get(quote, quote)}"
    for quote in _QUOTES:
        if text.endswith(quote) and len(text) > len(quote):
            base = text[: -len(quote)]
            return f"{_ASSETS.get(base, base)}/{_ASSETS.get(quote, quote)}"
    raise ValueError(f"cannot translate pair {pair!r} to a v2 symbol")


def executions_subscribe(
    *,
    token: str,
    snap_orders: bool,
    snap_trades: bool,
    req_id: int = 1,
) -> dict[str, Any]:
    return {
        "method": "subscribe",
        "req_id": req_id,
        "params": {
            "channel": "executions",
            "token": token,
            "snap_orders": snap_orders,
            "snap_trades": snap_trades,
            "order_status": True,
        },
    }


def execution_events(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize one executions snapshot or update. Other frames yield nothing."""
    if message.get("channel") != "executions":
        return []
    data = message.get("data")
    if not isinstance(data, list):
        return []
    msg_type = message.get("type")
    events: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            event = _one(item, msg_type)
            if event is not None:
                events.append(event)
    return events


def _one(item: dict[str, Any], msg_type: Any) -> dict[str, Any] | None:
    exec_type = item.get("exec_type")
    symbol = item.get("symbol")
    if isinstance(symbol, str) and symbol:
        try:
            symbol = to_v2_symbol(symbol)
            kind_class = asset_class(symbol)
        except ValueError:
            kind_class = "unknown"
    else:
        symbol = None
        kind_class = "unknown"
    if exec_type == "trade":
        fee = _fee(item)
        return {
            "kind": "own_trade",
            "source": "websocket",
            "type": msg_type,
            "exec_type": exec_type,
            "id": item.get("exec_id") or item.get("trade_id"),
            "trade_id": item.get("trade_id"),
            "order_id": item.get("order_id"),
            "symbol": symbol,
            "asset_class": kind_class,
            "side": item.get("side"),
            "order_type": item.get("order_type"),
            "price": _num(item.get("last_price")),
            "volume": _num(item.get("last_qty")),
            "cost": _num(item.get("cost")),
            "fee": fee,
            "maker": item.get("liquidity_ind") == "m",
            "time": item.get("timestamp"),
        }
    if not item.get("order_id"):
        return None
    status = item.get("order_status")
    return {
        "kind": "own_order",
        "source": "websocket",
        "type": msg_type,
        "exec_type": exec_type,
        "id": item.get("order_id"),
        "symbol": symbol,
        "asset_class": kind_class,
        "side": item.get("side"),
        "order_type": item.get("order_type"),
        "status": status,
        "price": _num(item.get("avg_price")),
        "limit_price": _num(item.get("limit_price")),
        "volume": _num(item.get("order_qty")),
        "volume_executed": _num(item.get("cum_qty")),
        "cost": _num(item.get("cum_cost")),
        "fee": _num(item.get("fee_usd_equiv")),
        "opened": item.get("timestamp") if status in {None, "pending_new", "new", "partially_filled"} else None,
        "closed": item.get("timestamp") if status in {"filled", "canceled", "expired"} else None,
        "time": item.get("timestamp"),
    }


async def stream_executions(
    emit: Emit,
    stop: asyncio.Event,
    *,
    token: str,
    url: str = AUTH_WS_URL,
    snap_orders: bool = True,
    snap_trades: bool = True,
    symbols: set[str] | None = None,
    follow: bool = False,
    duration: float | None = None,
    quiet_after: float = 1.5,
) -> int:
    """Subscribe and emit account events.

    Without `follow`, return once the snapshot has gone quiet. With `follow`,
    keep emitting live updates until `stop` or `duration`.
    """
    deadline = None if duration is None else time.monotonic() + duration
    emitted = 0
    async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=15, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps(executions_subscribe(token=token, snap_orders=snap_orders, snap_trades=snap_trades)))
        acked = False
        saw_snapshot = False
        quiet_at: float | None = None
        while not stop.is_set():
            timeout = _next_timeout(deadline, quiet_at if not follow else None)
            if timeout is not None and timeout <= 0:
                break
            raw = await _recv(ws, stop, timeout)
            if raw is None:
                if stop.is_set() or _reached(deadline):
                    break
                if not follow and (saw_snapshot or acked):
                    break
                continue
            message = json.loads(raw)
            if not isinstance(message, dict):
                continue
            if message.get("method") == "subscribe":
                acked = True
                if message.get("success") is False:
                    raise HistoryError(message.get("error") or "executions subscribe failed")
                quiet_at = time.monotonic() + quiet_after
                continue
            if message.get("channel") == "heartbeat":
                continue
            events = execution_events(message)
            if message.get("channel") == "executions" and message.get("type") == "snapshot":
                saw_snapshot = True
                quiet_at = time.monotonic() + quiet_after
            elif events and not follow:
                quiet_at = time.monotonic() + quiet_after
            for event in events:
                if symbols is not None and event.get("symbol") not in symbols:
                    continue
                emit(event)
                emitted += 1
            if not follow and saw_snapshot and quiet_at is not None and time.monotonic() >= quiet_at:
                break
    return emitted


def format_history_text(event: dict[str, Any]) -> str:
    if event.get("kind") == "own_trade":
        return (
            f"own-trade {event.get('type')} {event.get('asset_class')} {event.get('symbol')} "
            f"{event.get('side')} {_plain(event.get('volume'))} @ {_plain(event.get('price'))} "
            f"fee={_plain(event.get('fee'))} maker={str(event.get('maker')).lower()} "
            f"{event.get('time') or ''} id={event.get('id')}"
        )
    return (
        f"own-order {event.get('type')} {event.get('status')} {event.get('asset_class')} {event.get('symbol')} "
        f"{event.get('side')} {event.get('order_type')} "
        f"vol={_plain(event.get('volume'))} filled={_plain(event.get('volume_executed'))} "
        f"limit={_plain(event.get('limit_price'))} avg={_plain(event.get('price'))} "
        f"{event.get('time') or ''} id={event.get('id')}"
    )


def account_token() -> str:
    try:
        key, secret = load_credentials()
        return fetch_websocket_token(key, secret)
    except CredentialsError as exc:
        raise HistoryError(str(exc)) from exc


def _fee(item: dict[str, Any]) -> float | None:
    fees = item.get("fees")
    if isinstance(fees, list) and fees:
        total = 0.0
        seen = False
        for fee in fees:
            if isinstance(fee, dict) and fee.get("qty") is not None:
                total += float(fee["qty"])
                seen = True
        if seen:
            return total
    return _num(item.get("fee_usd_equiv"))


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _plain(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    text = format(float(value), ".10f").rstrip("0").rstrip(".")
    return text or "0"


def _reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _next_timeout(deadline: float | None, quiet_at: float | None) -> float | None:
    candidates = []
    now = time.monotonic()
    if deadline is not None:
        candidates.append(deadline - now)
    if quiet_at is not None:
        candidates.append(quiet_at - now)
    if not candidates:
        return None
    return max(0.0, min(candidates))


async def _recv(ws: Any, stop: asyncio.Event, timeout: float | None) -> str | bytes | None:
    recv_task = asyncio.create_task(ws.recv())
    stop_task = asyncio.create_task(stop.wait())
    try:
        done, _pending = await asyncio.wait(
            {recv_task, stop_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if recv_task in done:
            return recv_task.result()
        return None
    finally:
        for task in (recv_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(recv_task, stop_task, return_exceptions=True)
