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

"""Command-line entry for the public market-data consumer."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from typing import Any, TextIO

from krakentool import LICENSE_EPILOG, VersionAction
from krakentool.assets import asset_class
from krakentool.consumer import MarketDataConsumer
from krakentool.history import (
    HistoryError,
    account_token,
    format_history_text,
    stream_executions,
    to_v2_symbol,
)
from krakentool.protocol import AUTH_WS_URL as _AUTH_WS_URL
from krakentool.protocol import (
    BOOK_DEPTHS,
    EVENT_TRIGGERS,
    L3_DEPTHS,
    L3_WS_URL,
    MARKET_CHANNELS,
    OHLC_INTERVALS,
    PUBLIC_WS_URL,
    normalize_symbols,
)

DEFAULT_SYMBOLS = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "EUR/USD",
    "GBP/USD",
    "USD/JPY",
)


def format_text(event: dict[str, Any]) -> str:
    channel = event.get("channel")
    symbol = event.get("symbol", "?")
    kind = event.get("asset_class", "?")
    msg_type = event.get("type", "?")
    ts = event.get("timestamp") or event.get("interval_begin") or ""
    if channel == "ticker":
        return (
            f"ticker {msg_type} {kind} {symbol} "
            f"bid={_num(event.get('bid'))} x {_num(event.get('bid_qty'))} "
            f"ask={_num(event.get('ask'))} x {_num(event.get('ask_qty'))} "
            f"last={_num(event.get('last'))} "
            f"chg={_num(event.get('change_pct'))}% "
            f"{ts}"
        )
    if channel == "trade":
        return (
            f"trade {msg_type} {kind} {symbol} "
            f"{event.get('side')} {_num(event.get('qty'))} @ {_num(event.get('price'))} "
            f"id={event.get('trade_id')} {ts}"
        )
    if channel == "book":
        bids = event.get("bids") or []
        asks = event.get("asks") or []
        bid = bids[0] if bids else {}
        ask = asks[0] if asks else {}
        return (
            f"book {msg_type} {kind} {symbol} "
            f"bid={_num(bid.get('price'))} x {_num(bid.get('qty'))} "
            f"ask={_num(ask.get('price'))} x {_num(ask.get('qty'))} "
            f"levels={len(bids)}/{len(asks)} {ts}"
        )
    if channel == "level3":
        bids = event.get("bids") or []
        asks = event.get("asks") or []
        bid = bids[0] if bids else {}
        ask = asks[0] if asks else {}
        return (
            f"level3 {msg_type} {kind} {symbol} "
            f"bid={_num(bid.get('limit_price'))} x {_num(bid.get('order_qty'))} "
            f"ask={_num(ask.get('limit_price'))} x {_num(ask.get('order_qty'))} "
            f"orders={len(bids)}/{len(asks)} {ts}"
        )
    if channel == "ohlc":
        return (
            f"ohlc {msg_type} {kind} {symbol} "
            f"o={_num(event.get('open'))} h={_num(event.get('high'))} "
            f"l={_num(event.get('low'))} c={_num(event.get('close'))} "
            f"interval={event.get('interval')} {ts}"
        )
    return json.dumps(event, separators=(",", ":"), default=str)


def _num(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    text = format(float(value), ".10f").rstrip("0").rstrip(".")
    return text or "0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="krakentool",
        description=(
            "Consume Kraken Spot WebSocket API v2 market data. "
            "Crypto and forex share a socket. level3 is the authenticated "
            "per-order book on wss://ws-l3.kraken.com/v2."
        ),
        epilog=LICENSE_EPILOG,
    )
    parser.add_argument(
        "symbols",
        nargs="*",
        help=(
            "v2 symbols, space or comma separated. "
            f"Default: {', '.join(DEFAULT_SYMBOLS)}"
        ),
    )
    parser.add_argument(
        "--channels",
        default="ticker",
        help=f"Comma-separated channels ({', '.join(MARKET_CHANNELS)}). Default: ticker",
    )
    parser.add_argument(
        "--event-trigger",
        choices=EVENT_TRIGGERS,
        default="bbo",
        help="Ticker publish trigger. bbo updates on quote changes (default); trades updates on prints",
    )
    parser.add_argument(
        "--book-depth",
        type=int,
        choices=BOOK_DEPTHS,
        default=10,
        help="Price levels per side for the aggregated book channel",
    )
    parser.add_argument(
        "--l3-depth",
        type=int,
        choices=L3_DEPTHS,
        default=10,
        help="Price levels per side for the level3 channel (10, 100, or 1000)",
    )
    parser.add_argument(
        "--l3-url",
        default=L3_WS_URL,
        help=f"Level 3 WebSocket URL (default: {L3_WS_URL})",
    )
    parser.add_argument(
        "--ohlc-interval",
        type=int,
        choices=OHLC_INTERVALS,
        default=1,
        help="Candle size in minutes for the ohlc channel",
    )
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Skip the initial snapshot and wait for live updates",
    )
    parser.add_argument(
        "--url",
        default=PUBLIC_WS_URL,
        help=f"Public WebSocket URL (default: {PUBLIC_WS_URL})",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="stdout format. json is one object per line",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Exit after this many seconds",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="Exit after this many market-data events",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit if any symbol subscription is rejected",
    )
    parser.add_argument(
        "--ping-interval",
        type=float,
        default=30.0,
        help="Seconds between application-level pings (Kraken requires < 60)",
    )
    parser.add_argument("--version", action=VersionAction)
    return parser


def main(argv: list[str] | None = None, out: TextIO | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "history":
        return history_main(args_list[1:], out)
    if args_list and args_list[0] == "dataset":
        from krakentool.dataset import dataset_main

        return dataset_main(args_list[1:])
    args = build_parser().parse_args(args_list)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if args.ping_interval <= 0 or args.ping_interval >= 60:
        print("ping interval must be between 0 and 60 seconds", file=sys.stderr)
        return 2
    try:
        symbols = normalize_symbols(args.symbols or DEFAULT_SYMBOLS)
        channels = [part.strip() for part in args.channels.split(",") if part.strip()]
        consumer = MarketDataConsumer(
            symbols,
            channels,
            url=args.url,
            snapshot=not args.no_snapshot,
            event_trigger=args.event_trigger,
            book_depth=args.book_depth,
            l3_depth=args.l3_depth,
            l3_url=args.l3_url,
            token_factory=account_token if "level3" in channels else None,
            ohlc_interval=args.ohlc_interval,
            ping_interval=args.ping_interval,
            strict=args.strict,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    classes = {asset_class(symbol) for symbol in symbols}
    logging.getLogger("krakentool").info(
        "watching %s (%s)",
        " ".join(symbols),
        ", ".join(sorted(classes)),
    )
    sink = out or sys.stdout
    return asyncio.run(
        _run(
            consumer,
            sink,
            fmt=args.format,
            duration=args.duration,
            max_messages=args.max_messages,
        )
    )


async def _run(
    consumer: MarketDataConsumer,
    out: TextIO,
    *,
    fmt: str,
    duration: float | None,
    max_messages: int | None,
) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    def emit(event: dict[str, Any]) -> None:
        if fmt == "text":
            line = format_text(event)
        else:
            line = json.dumps(event, separators=(",", ":"), default=str)
        print(line, file=out, flush=True)

    try:
        count = await consumer.run(
            emit,
            stop,
            duration=duration,
            max_messages=max_messages,
        )
    except Exception as exc:
        logging.getLogger("krakentool").error("%s", exc)
        return 1
    logging.getLogger("krakentool").info("stopped after %d market events", count)
    return 0


def history_main(argv: list[str], out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="krakentool history",
        description=(
            "Your Kraken spot fills and orders over the authenticated "
            "WebSocket v2 executions channel. The snapshot is open orders "
            "plus the latest 50 fills; --follow keeps the live updates."
        ),
        epilog=LICENSE_EPILOG,
    )
    parser.add_argument(
        "symbols",
        nargs="*",
        help="Optional v2 or REST symbols to keep, for example BTC/USD or XXBTZUSD",
    )
    parser.add_argument(
        "--trades",
        action="store_true",
        help="Fills only. With neither --trades nor --orders, both are included",
    )
    parser.add_argument("--orders", action="store_true", help="Order events only")
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not request the open-order snapshot",
    )
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Stay connected and print live order and fill updates",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop after this many seconds",
    )
    parser.add_argument(
        "--url",
        default=_AUTH_WS_URL,
        help=f"Authenticated WebSocket URL (default: {_AUTH_WS_URL})",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="json",
        help="stdout format. json is one object per line",
    )
    parser.add_argument("--version", action=VersionAction)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    want_trades = args.trades or not args.orders
    want_orders = args.orders or not args.trades
    if args.no_open:
        want_orders = False
    try:
        symbols = {to_v2_symbol(symbol) for symbol in args.symbols} or None
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sink = out or sys.stdout
    try:
        count = asyncio.run(
            _history_run(
                sink,
                fmt=args.format,
                url=args.url,
                snap_orders=want_orders,
                snap_trades=want_trades,
                symbols=symbols,
                follow=args.follow,
                duration=args.duration,
            )
        )
    except HistoryError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    logging.getLogger("krakentool").info("wrote %d account events", count)
    return 0


async def _history_run(
    out: TextIO,
    *,
    fmt: str,
    url: str,
    snap_orders: bool,
    snap_trades: bool,
    symbols: set[str] | None,
    follow: bool,
    duration: float | None,
) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    def emit(event: dict[str, Any]) -> None:
        if fmt == "text":
            line = format_history_text(event)
        else:
            line = json.dumps(event, separators=(",", ":"), default=str)
        print(line, file=out, flush=True)

    token = account_token()
    logging.getLogger("krakentool").info(
        "executions %s snap_orders=%s snap_trades=%s",
        url,
        snap_orders,
        snap_trades,
    )
    return await stream_executions(
        emit,
        stop,
        token=token,
        url=url,
        snap_orders=snap_orders,
        snap_trades=snap_trades,
        symbols=symbols,
        follow=follow,
        duration=duration,
    )
