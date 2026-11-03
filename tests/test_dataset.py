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

import unittest

from krakentool.dataset import (
    DatasetError,
    apply_gaps,
    fetch_ohlcv,
    fetch_trades,
    parse_bound,
    validate_vwap,
    _ohlc_args,
    _trade_args,
)


def _candle(opened: int, close: float = 10.0, *, vwap: float | None = None, volume: float = 1.0, count: int = 1) -> dict:
    return {
        "time": opened,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "vwap": close if vwap is None else vwap,
        "volume": volume,
        "count": count,
    }


class BoundTests(unittest.TestCase):
    def test_date_is_utc_midnight(self) -> None:
        self.assertEqual(parse_bound("2024-01-02"), 1704153600)
        self.assertEqual(parse_bound("1704153600"), 1704153600)
        self.assertEqual(parse_bound("2024-01-02T00:20:00Z"), 1704154800)
        with self.assertRaises(DatasetError):
            parse_bound("yesterday")


class PaginationTests(unittest.TestCase):
    def test_ohlc_advances_with_last_and_stops_at_end(self) -> None:
        calls: list[int] = []

        def runner(args: list[str]) -> dict:
            since = int(args[args.index("--since") + 1])
            calls.append(since)
            pages = {
                1000: {"last": 1120, "candles": [_candle(1000), _candle(1060), _candle(1120)]},
                1120: {"last": 1240, "candles": [_candle(1120), _candle(1180), _candle(1240)]},
                1240: {"last": 1240, "candles": [_candle(1240)]},
            }
            return pages[since]

        candles, truncated = fetch_ohlcv(
            runner, "BTC/USD", interval_minutes=1, start=1000, end=1200, pause=0
        )
        self.assertEqual([row["time"] for row in candles], [1000, 1060, 1120, 1180])
        self.assertEqual(calls, [1000, 1120])
        self.assertFalse(truncated)
        self.assertEqual(candles[0]["asset_class"], "crypto")
        self.assertFalse(candles[0]["gap"])

    def test_trades_stop_after_the_window_and_dedupe(self) -> None:
        def runner(args: list[str]) -> dict:
            since = args[args.index("--since") + 1]
            if since == "100":
                return {
                    "last": 200,
                    "trades": [
                        {"price": 1, "volume": 1, "time": "110.5", "side": "buy", "order_type": "limit", "trade_id": 1},
                        {"price": 2, "volume": 1, "time": "150.0", "side": "sell", "order_type": "market", "trade_id": 2},
                    ],
                }
            if since == "200":
                return {
                    "last": 400,
                    "trades": [
                        {"price": 2, "volume": 1, "time": "150.0", "side": "sell", "order_type": "market", "trade_id": 2},
                        {"price": 3, "volume": 1, "time": "250.0", "side": "buy", "order_type": "limit", "trade_id": 3},
                    ],
                }
            raise AssertionError(since)

        trades, truncated = fetch_trades(runner, "EUR/USD", start=100, end=200, pause=0)
        self.assertEqual([row["trade_id"] for row in trades], [1, 2])
        self.assertEqual(trades[0]["asset_class"], "forex")
        self.assertFalse(truncated)
        self.assertIn("--asset-class", _trade_args("EUR/USD", 1))
        self.assertNotIn("--asset-class", _ohlc_args("BTC/USD", 1440, 1))


class GapTests(unittest.TestCase):
    def test_forward_fill_uses_previous_close(self) -> None:
        candles, _truncated = fetch_ohlcv(
            lambda _args: {"last": 120, "candles": [_candle(0, 5), _candle(120, 9)]},
            "BTC/USD",
            interval_minutes=1,
            start=0,
            end=180,
        )
        filled, gaps = apply_gaps(candles, interval_seconds=60, policy="forward-fill")
        self.assertEqual(gaps, [60])
        self.assertEqual([row["time"] for row in filled], [0, 60, 120])
        self.assertEqual(filled[1]["close"], 5)
        self.assertEqual(filled[1]["volume"], 0)
        self.assertTrue(filled[1]["gap"])

    def test_exclude_lists_the_hole_and_drops_it(self) -> None:
        candles = [
            {"symbol": "EUR/USD", "asset_class": "forex", "interval": 1, "time": 0, "close": 1.1, "gap": False},
            {"symbol": "EUR/USD", "asset_class": "forex", "interval": 1, "time": 120, "close": 1.2, "gap": False},
        ]
        kept, gaps = apply_gaps(candles, interval_seconds=60, policy="exclude")
        self.assertEqual(gaps, [60])
        self.assertEqual([row["time"] for row in kept], [0, 120])


class VwapTests(unittest.TestCase):
    def test_matching_ticks_pass(self) -> None:
        candles = [
            {
                "symbol": "BTC/USD",
                "time": 60,
                "time_iso": "t",
                "vwap": 10.0,
                "volume": 3.0,
                "count": 2,
                "gap": False,
            }
        ]
        trades = [
            {"time": 61.0, "price": 8.0, "volume": 1.0},
            {"time": 70.0, "price": 11.0, "volume": 2.0},
        ]
        report = validate_vwap(candles, trades, interval_seconds=60, tick_start=60, tick_end=120)
        self.assertTrue(report[0]["ok"])
        self.assertEqual(report[0]["tick_vwap"], 10.0)
        self.assertEqual(report[0]["tick_count"], 2)

    def test_missing_tick_page_fails(self) -> None:
        candles = [
            {
                "symbol": "BTC/USD",
                "time": 60,
                "vwap": 10.0,
                "volume": 3.0,
                "count": 2,
                "gap": False,
            }
        ]
        trades = [{"time": 61.0, "price": 8.0, "volume": 1.0}]
        report = validate_vwap(candles, trades, interval_seconds=60, tick_start=60, tick_end=120)
        self.assertFalse(report[0]["ok"])
        self.assertEqual(report[0]["tick_count"], 1)
        self.assertEqual(report[0]["candle_count"], 2)
