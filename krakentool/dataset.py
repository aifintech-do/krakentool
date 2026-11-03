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

"""Build a backtesting dataset from Kraken public OHLC and trade history.

OHLC and trade pages both advance with the `last` cursor from the previous
response. Spot OHLC serves at most 720 candles per interval, so a daily series
is the long window and minute candles are a drill-down inside it. Trade ticks
are checked against each candle's VWAP and trade count. Missing candles are
either left out or forward-filled from the previous close.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from krakentool.assets import asset_class

DAILY_MINUTES = 1440
MINUTE_MINUTES = 1
Runner = Callable[[list[str]], dict[str, Any]]


class DatasetError(RuntimeError):
    """A public history request failed or the requested window is invalid."""


def parse_bound(value: str) -> int:
    """Unix seconds from an integer timestamp, YYYY-MM-DD, or UTC ISO-8601."""
    text = value.strip()
    if text.isdigit():
        return int(text)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            when = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return int(when.timestamp())
    raise DatasetError(
        f"expected YYYY-MM-DD, YYYY-MM-DDTHH:MM:SSZ, or unix seconds, got {value!r}"
    )


def fetch_ohlcv(
    runner: Runner,
    symbol: str,
    *,
    interval_minutes: int,
    start: int,
    end: int,
    max_pages: int = 10,
    pause: float = 0.0,
) -> tuple[list[dict[str, Any]], bool]:
    """Page OHLC with each response's `last` cursor. Returns candles and truncated."""
    if start >= end:
        raise DatasetError("start must be before end")
    since = start
    previous: int | None = None
    by_time: dict[int, dict[str, Any]] = {}
    truncated = False
    for page in range(max_pages):
        payload = runner(_ohlc_args(symbol, interval_minutes, since))
        raw_candles = payload.get("candles") or []
        if not raw_candles:
            break
        cursor = _cursor(payload.get("last"))
        for raw in raw_candles:
            if not isinstance(raw, dict) or raw.get("time") is None:
                continue
            opened = int(raw["time"])
            if opened < start or opened >= end or opened in by_time:
                continue
            by_time[opened] = _candle(symbol, interval_minutes, raw)
        if cursor is None or cursor == previous or cursor == since or cursor >= end:
            break
        previous = cursor
        since = cursor
        if page + 1 == max_pages and cursor < end:
            truncated = True
            break
        if pause:
            time.sleep(pause)
    candles = [by_time[key] for key in sorted(by_time)]
    return candles, truncated


def fetch_trades(
    runner: Runner,
    symbol: str,
    *,
    start: int,
    end: int,
    max_pages: int = 30,
    pause: float = 0.0,
) -> tuple[list[dict[str, Any]], bool]:
    """Page public trades with each response's `last` cursor."""
    if start >= end:
        raise DatasetError("start must be before end")
    since: int | str = start
    previous: int | None = None
    by_id: dict[int, dict[str, Any]] = {}
    truncated = False
    for page in range(max_pages):
        payload = runner(_trade_args(symbol, since))
        raw_trades = payload.get("trades") or []
        if not raw_trades:
            break
        cursor = _cursor(payload.get("last"))
        reached_end = False
        for raw in raw_trades:
            if not isinstance(raw, dict):
                continue
            stamp = float(raw["time"])
            if stamp >= end:
                reached_end = True
                continue
            if stamp < start:
                continue
            trade_id = int(raw["trade_id"])
            by_id[trade_id] = _trade(symbol, raw, stamp)
        if reached_end or cursor is None or cursor == previous:
            break
        previous = cursor
        since = cursor
        if page + 1 == max_pages:
            truncated = True
            break
        if pause:
            time.sleep(pause)
    trades = sorted(by_id.values(), key=lambda row: (row["time"], row["trade_id"]))
    return trades, truncated


def apply_gaps(
    candles: list[dict[str, Any]],
    *,
    interval_seconds: int,
    policy: str,
) -> tuple[list[dict[str, Any]], list[int]]:
    """Find holes between the first and last candle.

    `exclude` leaves those minutes out. `forward-fill` inserts a flat candle
    at the previous close with zero volume so a continuous index still exists.
    """
    if policy not in {"exclude", "forward-fill"}:
        raise DatasetError("gaps must be exclude or forward-fill")
    if not candles:
        return [], []
    ordered = sorted(candles, key=lambda row: row["time"])
    have = {int(row["time"]): row for row in ordered}
    first = int(ordered[0]["time"])
    last = int(ordered[-1]["time"])
    gaps: list[int] = []
    filled: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    opened = first
    while opened <= last:
        if opened in have:
            row = dict(have[opened])
            row["gap"] = False
            filled.append(row)
            previous = row
        else:
            gaps.append(opened)
            if policy == "forward-fill" and previous is not None:
                close = previous["close"]
                synthetic = {
                    "symbol": previous["symbol"],
                    "asset_class": previous["asset_class"],
                    "interval": previous["interval"],
                    "time": opened,
                    "time_iso": _iso(opened),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "vwap": close,
                    "volume": 0.0,
                    "count": 0,
                    "gap": True,
                }
                filled.append(synthetic)
                previous = synthetic
        opened += interval_seconds
    if policy == "exclude":
        filled = [row for row in filled if not row["gap"]]
    return filled, gaps


def validate_vwap(
    candles: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    *,
    interval_seconds: int,
    tick_start: int,
    tick_end: int,
    tolerance: float = 1e-4,
) -> list[dict[str, Any]]:
    """Compare tick VWAP, volume, and count with candles fully inside the tick window."""
    buckets: dict[int, list[dict[str, Any]]] = {}
    for trade in trades:
        opened = int(trade["time"] // interval_seconds) * interval_seconds
        buckets.setdefault(opened, []).append(trade)
    reports: list[dict[str, Any]] = []
    for candle in candles:
        if candle.get("gap"):
            continue
        opened = int(candle["time"])
        if opened < tick_start or opened + interval_seconds > tick_end:
            continue
        group = buckets.get(opened, [])
        tick_volume = sum(float(trade["volume"]) for trade in group)
        tick_notional = sum(float(trade["price"]) * float(trade["volume"]) for trade in group)
        tick_vwap = tick_notional / tick_volume if tick_volume else None
        candle_vwap = float(candle["vwap"])
        candle_volume = float(candle["volume"])
        vwap_err = None
        if tick_vwap is not None and candle_vwap:
            vwap_err = abs(tick_vwap - candle_vwap) / abs(candle_vwap)
        volume_err = None
        if candle_volume:
            volume_err = abs(tick_volume - candle_volume) / abs(candle_volume)
        count_ok = len(group) == int(candle["count"])
        vwap_ok = vwap_err is not None and vwap_err <= tolerance
        volume_ok = volume_err is not None and volume_err <= tolerance
        if int(candle["count"]) == 0 and not group:
            count_ok = vwap_ok = volume_ok = True
            vwap_err = 0.0
        reports.append(
            {
                "time": opened,
                "time_iso": candle.get("time_iso") or _iso(opened),
                "symbol": candle["symbol"],
                "candle_vwap": candle_vwap,
                "tick_vwap": tick_vwap,
                "vwap_rel_err": vwap_err,
                "candle_volume": candle_volume,
                "tick_volume": tick_volume,
                "candle_count": int(candle["count"]),
                "tick_count": len(group),
                "ok": bool(count_ok and vwap_ok and volume_ok),
            }
        )
    return reports


def build_symbol(
    runner: Runner,
    symbol: str,
    *,
    start: int,
    end: int,
    drill_start: int | None = None,
    drill_end: int | None = None,
    minutes: bool = False,
    ticks: bool = False,
    gaps: str = "exclude",
    tolerance: float = 1e-4,
    pause: float = 0.0,
    max_trade_pages: int = 30,
) -> dict[str, Any]:
    """Daily candles, optional minute candles and ticks, gap policy, VWAP check."""
    if drill_start is None:
        drill_start = start
    if drill_end is None:
        drill_end = end
    daily, daily_truncated = fetch_ohlcv(
        runner,
        symbol,
        interval_minutes=DAILY_MINUTES,
        start=start,
        end=end,
        pause=pause,
    )
    daily, daily_gaps = apply_gaps(daily, interval_seconds=DAILY_MINUTES * 60, policy=gaps)
    minute: list[dict[str, Any]] = []
    minute_gaps: list[int] = []
    minute_truncated = False
    if minutes:
        minute, minute_truncated = fetch_ohlcv(
            runner,
            symbol,
            interval_minutes=MINUTE_MINUTES,
            start=drill_start,
            end=drill_end,
            pause=pause,
        )
        minute, minute_gaps = apply_gaps(minute, interval_seconds=60, policy=gaps)
    trades: list[dict[str, Any]] = []
    trades_truncated = False
    validation: list[dict[str, Any]] = []
    if ticks:
        trades, trades_truncated = fetch_trades(
            runner,
            symbol,
            start=drill_start,
            end=drill_end,
            max_pages=max_trade_pages,
            pause=pause,
        )
        target = minute if minutes else [row for row in daily if not row.get("gap")]
        interval = 60 if minutes else DAILY_MINUTES * 60
        validation = validate_vwap(
            target,
            trades,
            interval_seconds=interval,
            tick_start=drill_start,
            tick_end=drill_end,
            tolerance=tolerance,
        )
    failed = [row for row in validation if not row["ok"]]
    return {
        "symbol": symbol,
        "asset_class": asset_class(symbol),
        "daily": daily,
        "daily_gaps": daily_gaps,
        "daily_truncated": daily_truncated,
        "minute": minute,
        "minute_gaps": minute_gaps,
        "minute_truncated": minute_truncated,
        "trades": trades,
        "trades_truncated": trades_truncated,
        "validation": validation,
        "validation_failed": len(failed),
    }


def write_dataset(result: dict[str, Any], out_dir: Path, *, gaps: str, tolerance: float) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gaps": gaps,
        "vwap_tolerance": tolerance,
        "ohlc_page_limit": 720,
        "symbols": [],
    }
    for item in result["symbols"]:
        folder = out_dir / item["symbol"].replace("/", "-")
        folder.mkdir(parents=True, exist_ok=True)
        _write_jsonl(folder / "ohlcv-1d.jsonl", item["daily"])
        if item["minute"]:
            _write_jsonl(folder / "ohlcv-1m.jsonl", item["minute"])
        if item["trades"]:
            _write_jsonl(folder / "trades.jsonl", item["trades"])
        _write_jsonl(folder / "validation.jsonl", item["validation"])
        (folder / "gaps.json").write_text(
            json.dumps(
                {"daily": item["daily_gaps"], "minute": item["minute_gaps"]},
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        errs = [row["vwap_rel_err"] for row in item["validation"] if isinstance(row.get("vwap_rel_err"), float)]
        summary["symbols"].append(
            {
                "symbol": item["symbol"],
                "asset_class": item["asset_class"],
                "daily_candles": len(item["daily"]),
                "daily_gaps": len(item["daily_gaps"]),
                "daily_truncated": item["daily_truncated"],
                "minute_candles": len(item["minute"]),
                "minute_gaps": len(item["minute_gaps"]),
                "minute_truncated": item["minute_truncated"],
                "trades": len(item["trades"]),
                "trades_truncated": item["trades_truncated"],
                "vwap_checked": len(item["validation"]),
                "vwap_failed": item["validation_failed"],
                "max_vwap_rel_err": max(errs) if errs else None,
            }
        )
    manifest = out_dir / "manifest.json"
    manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return manifest


def dataset_main(argv: list[str]) -> int:
    import argparse
    import logging
    import sys

    from krakentool import LICENSE_EPILOG, VersionAction
    from krakentool.protocol import normalize_symbols

    parser = argparse.ArgumentParser(
        prog="krakentool dataset",
        description=(
            "Collect a backtesting dataset. Daily OHLC is paged with the "
            "response last cursor, then optional minute candles and trade "
            "ticks for a drill-down window. Ticks are checked against candle VWAP."
        ),
        epilog=LICENSE_EPILOG,
    )
    parser.add_argument("symbols", nargs="+", help="v2 symbols, for example BTC/USD EUR/USD")
    parser.add_argument("--start", required=True, help="UTC date YYYY-MM-DD or unix seconds")
    parser.add_argument("--end", required=True, help="UTC date YYYY-MM-DD or unix seconds, exclusive")
    parser.add_argument("--drill-start", help="Minute and tick window start; default is --start")
    parser.add_argument("--drill-end", help="Minute and tick window end; default is --end")
    parser.add_argument("--minutes", action="store_true", help="Also collect 1-minute candles for the drill window")
    parser.add_argument("--ticks", action="store_true", help="Also collect trade ticks for the drill window")
    parser.add_argument(
        "--gaps",
        choices=("exclude", "forward-fill"),
        default="exclude",
        help="Missing candles: leave them out, or insert the previous close (default: exclude)",
    )
    parser.add_argument("--vwap-tolerance", type=float, default=1e-4, help="Relative VWAP error allowed in the tick check")
    parser.add_argument("--pause", type=float, default=0.25, help="Seconds between public REST pages")
    parser.add_argument("--max-trade-pages", type=int, default=30, help="Trade pages of 1000 before stopping")
    parser.add_argument("--out", default="dataset", help="Output directory")
    parser.add_argument("--version", action=VersionAction)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        symbols = normalize_symbols(args.symbols)
        start = parse_bound(args.start)
        end = parse_bound(args.end)
        drill_start = parse_bound(args.drill_start) if args.drill_start else None
        drill_end = parse_bound(args.drill_end) if args.drill_end else None
        if args.vwap_tolerance < 0:
            raise DatasetError("vwap tolerance must be >= 0")
        runner = kraken_runner()
        built = []
        for symbol in symbols:
            logging.getLogger("krakentool").info("collecting %s", symbol)
            built.append(
                build_symbol(
                    runner,
                    symbol,
                    start=start,
                    end=end,
                    drill_start=drill_start,
                    drill_end=drill_end,
                    minutes=args.minutes,
                    ticks=args.ticks,
                    gaps=args.gaps,
                    tolerance=args.vwap_tolerance,
                    pause=args.pause,
                    max_trade_pages=args.max_trade_pages,
                )
            )
        manifest = write_dataset(
            {"symbols": built},
            Path(args.out),
            gaps=args.gaps,
            tolerance=args.vwap_tolerance,
        )
    except (DatasetError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(manifest)
    for item in built:
        logging.getLogger("krakentool").info(
            "%s daily=%d minute=%d trades=%d vwap_failed=%d",
            item["symbol"],
            len(item["daily"]),
            len(item["minute"]),
            len(item["trades"]),
            item["validation_failed"],
        )
    return 0


def kraken_runner(bin_name: str = "kraken") -> Runner:
    binary = shutil.which(bin_name)
    if binary is None:
        raise DatasetError("kraken is not on PATH")

    def run(args: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            [binary, "-o", "json", "--log-format", "compact", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise DatasetError(detail or f"kraken {' '.join(args)} failed")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise DatasetError(f"kraken {' '.join(args)} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DatasetError(f"kraken {' '.join(args)} returned an unexpected payload")
        error = payload.get("error")
        if isinstance(error, list) and error:
            raise DatasetError("; ".join(str(item) for item in error))
        if isinstance(error, str) and error:
            raise DatasetError(error)
        return payload

    return run


def _ohlc_args(symbol: str, interval_minutes: int, since: int) -> list[str]:
    args = ["ohlc", symbol, "--interval", str(interval_minutes), "--since", str(since)]
    if asset_class(symbol) == "forex":
        args.extend(["--asset-class", "forex"])
    return args


def _trade_args(symbol: str, since: int | str) -> list[str]:
    args = ["trades", symbol, "--since", str(since), "--count", "1000"]
    if asset_class(symbol) == "forex":
        args.extend(["--asset-class", "forex"])
    return args


def _cursor(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _candle(symbol: str, interval_minutes: int, raw: dict[str, Any]) -> dict[str, Any]:
    opened = int(raw["time"])
    return {
        "symbol": symbol,
        "asset_class": asset_class(symbol),
        "interval": interval_minutes,
        "time": opened,
        "time_iso": _iso(opened),
        "open": float(raw["open"]),
        "high": float(raw["high"]),
        "low": float(raw["low"]),
        "close": float(raw["close"]),
        "vwap": float(raw["vwap"]),
        "volume": float(raw["volume"]),
        "count": int(raw["count"]),
        "gap": False,
    }


def _trade(symbol: str, raw: dict[str, Any], stamp: float) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "asset_class": asset_class(symbol),
        "time": stamp,
        "time_iso": _iso(stamp),
        "price": float(raw["price"]),
        "volume": float(raw["volume"]),
        "side": raw.get("side"),
        "order_type": raw.get("order_type"),
        "trade_id": int(raw["trade_id"]),
    }


def _iso(stamp: float) -> str:
    when = datetime.fromtimestamp(float(stamp), timezone.utc)
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond:06d}Z"


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
