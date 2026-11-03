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

from krakentool.assets import asset_class
from krakentool.protocol import (
    build_subscriptions,
    control_summary,
    market_events,
    normalize_symbols,
    ping,
)


class SymbolTests(unittest.TestCase):
    def test_mixed_asset_classes(self) -> None:
        self.assertEqual(asset_class("btc/usd"), "crypto")
        self.assertEqual(asset_class("ETH/EUR"), "crypto")
        self.assertEqual(asset_class("EUR/USD"), "forex")
        self.assertEqual(asset_class("gbp/jpy"), "forex")
        self.assertEqual(asset_class("USDT/USD"), "crypto")
        self.assertEqual(asset_class("EURC/EUR"), "crypto")

    def test_normalize_dedupes_and_splits_commas(self) -> None:
        self.assertEqual(
            normalize_symbols(["btc/usd, EUR/USD", "BTC/USD", "eth/usd"]),
            ["BTC/USD", "EUR/USD", "ETH/USD"],
        )

    def test_rejects_legacy_rest_names(self) -> None:
        with self.assertRaises(ValueError):
            normalize_symbols(["XBTUSD"])


class SubscribeTests(unittest.TestCase):
    def test_ticker_and_trade_frames(self) -> None:
        frames = build_subscriptions(
            ["BTC/USD", "EUR/USD"],
            ["ticker", "trade"],
            event_trigger="bbo",
            snapshot=True,
        )
        self.assertEqual([frame["req_id"] for frame in frames], [1, 2])
        ticker = frames[0]["params"]
        self.assertEqual(ticker["channel"], "ticker")
        self.assertEqual(ticker["symbol"], ["BTC/USD", "EUR/USD"])
        self.assertEqual(ticker["event_trigger"], "bbo")
        self.assertTrue(ticker["snapshot"])
        self.assertEqual(frames[1]["params"]["channel"], "trade")
        self.assertNotIn("event_trigger", frames[1]["params"])

    def test_book_and_ohlc_options_and_chunking(self) -> None:
        symbols = [f"P{i}/USD" for i in range(3)]
        frames = build_subscriptions(
            symbols,
            ["book", "ohlc"],
            book_depth=25,
            ohlc_interval=5,
            chunk_size=2,
        )
        self.assertEqual(len(frames), 4)
        self.assertEqual(frames[0]["params"]["symbol"], ["P0/USD", "P1/USD"])
        self.assertEqual(frames[0]["params"]["depth"], 25)
        self.assertEqual(frames[2]["params"]["channel"], "ohlc")
        self.assertEqual(frames[2]["params"]["interval"], 5)

    def test_level3_requires_token_and_uses_its_own_depth(self) -> None:
        with self.assertRaises(ValueError):
            build_subscriptions(["BTC/USD"], ["level3"])
        frames = build_subscriptions(
            ["BTC/USD", "EUR/USD"],
            ["level3"],
            l3_depth=100,
            token="ws-token",
        )
        params = frames[0]["params"]
        self.assertEqual(params["channel"], "level3")
        self.assertEqual(params["depth"], 100)
        self.assertEqual(params["token"], "ws-token")
        self.assertEqual(params["symbol"], ["BTC/USD", "EUR/USD"])
        with self.assertRaises(ValueError):
            build_subscriptions(["BTC/USD"], ["level3"], l3_depth=25, token="ws-token")

    def test_level3_snapshot_keeps_individual_orders(self) -> None:
        events = market_events(
            {
                "channel": "level3",
                "type": "snapshot",
                "data": [
                    {
                        "symbol": "EUR/USD",
                        "checksum": 1,
                        "bids": [
                            {"order_id": "B1", "limit_price": 1.1, "order_qty": 10},
                        ],
                        "asks": [
                            {"order_id": "A1", "limit_price": 1.2, "order_qty": 4},
                        ],
                    }
                ],
            }
        )
        self.assertEqual(events[0]["asset_class"], "forex")
        self.assertEqual(events[0]["channel"], "level3")
        self.assertEqual(events[0]["bids"][0]["order_id"], "B1")
        update = market_events(
            {
                "channel": "level3",
                "type": "update",
                "data": [
                    {
                        "symbol": "BTC/USD",
                        "bids": [],
                        "asks": [
                            {
                                "event": "delete",
                                "order_id": "A2",
                                "limit_price": 100,
                                "order_qty": 0.1,
                            }
                        ],
                    }
                ],
            }
        )
        self.assertEqual(update[0]["asset_class"], "crypto")
        self.assertEqual(update[0]["asks"][0]["event"], "delete")

    def test_ping_req_id(self) -> None:
        self.assertEqual(ping(7), {"method": "ping", "req_id": 7})
        with self.assertRaises(ValueError):
            ping(0)


class ParseTests(unittest.TestCase):
    def test_ticker_snapshot_is_tagged_with_asset_class(self) -> None:
        message = {
            "channel": "ticker",
            "type": "snapshot",
            "data": [
                {
                    "symbol": "EUR/USD",
                    "bid": 1.11541,
                    "ask": 1.11544,
                    "last": 1.11544,
                    "timestamp": "2026-11-01T00:12:55.023969Z",
                },
                {"symbol": "BTC/USD", "bid": 77390.0, "ask": 77390.1, "last": 77390.0},
            ],
        }
        events = market_events(message)
        self.assertEqual([event["asset_class"] for event in events], ["forex", "crypto"])
        self.assertEqual(events[0]["channel"], "ticker")
        self.assertEqual(events[0]["type"], "snapshot")
        self.assertEqual(events[0]["bid"], 1.11541)
        self.assertIsNone(control_summary(message))

    def test_trade_update(self) -> None:
        events = market_events(
            {
                "channel": "trade",
                "type": "update",
                "data": [
                    {
                        "symbol": "GBP/USD",
                        "side": "buy",
                        "price": 1.3375,
                        "qty": 10.0,
                        "trade_id": 42,
                    }
                ],
            }
        )
        self.assertEqual(events[0]["asset_class"], "forex")
        self.assertEqual(events[0]["trade_id"], 42)

    def test_control_frames_are_not_market_data(self) -> None:
        status = {
            "channel": "status",
            "type": "update",
            "data": [{"api_version": "v2", "system": "online", "version": "2.0.10"}],
        }
        heartbeat = {"channel": "heartbeat"}
        ack = {
            "method": "subscribe",
            "success": True,
            "result": {"channel": "ticker", "symbol": "EUR/USD"},
            "req_id": 1,
        }
        rejected = {
            "method": "subscribe",
            "success": False,
            "error": "Currency pair not supported",
            "result": {"channel": "ticker", "symbol": "NOPE/USD"},
        }
        self.assertEqual(market_events(status), [])
        self.assertEqual(market_events(heartbeat), [])
        self.assertEqual(control_summary(status)["api_version"], "v2")
        self.assertEqual(control_summary(heartbeat), {"kind": "heartbeat"})
        self.assertTrue(control_summary(ack)["success"])
        self.assertEqual(control_summary(rejected)["symbol"], "NOPE/USD")
        self.assertIn("not supported", control_summary(rejected)["error"])


if __name__ == "__main__":
    unittest.main()
