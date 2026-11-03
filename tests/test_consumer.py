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

import asyncio
import json
import unittest

import websockets

from krakentool.consumer import MarketDataConsumer


class LocalFeedTests(unittest.IsolatedAsyncioTestCase):
    async def test_consumer_emits_crypto_and_forex_then_stops(self) -> None:
        received: list[dict] = []

        async def handler(ws):
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            subscribe = json.loads(raw)
            self.assertEqual(subscribe["method"], "subscribe")
            self.assertEqual(subscribe["params"]["channel"], "ticker")
            self.assertEqual(subscribe["params"]["symbol"], ["BTC/USD", "EUR/USD"])
            self.assertEqual(subscribe["params"]["event_trigger"], "bbo")
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "success": True,
                        "req_id": subscribe["req_id"],
                        "result": {"channel": "ticker", "symbol": "BTC/USD", "snapshot": True},
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "success": True,
                        "req_id": subscribe["req_id"],
                        "result": {"channel": "ticker", "symbol": "EUR/USD", "snapshot": True},
                    }
                )
            )
            await ws.send(json.dumps({"channel": "heartbeat"}))
            await ws.send(
                json.dumps(
                    {
                        "channel": "ticker",
                        "type": "snapshot",
                        "data": [
                            {"symbol": "BTC/USD", "bid": 100.0, "ask": 101.0, "last": 100.5},
                            {"symbol": "EUR/USD", "bid": 1.1, "ask": 1.2, "last": 1.15},
                        ],
                    }
                )
            )
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            consumer = MarketDataConsumer(
                ["BTC/USD", "EUR/USD"],
                ["ticker"],
                url=f"ws://127.0.0.1:{port}",
                ping_interval=30,
            )
            count = await consumer.run(
                received.append,
                asyncio.Event(),
                max_messages=2,
            )

        self.assertEqual(count, 2)
        self.assertEqual(
            [(event["symbol"], event["asset_class"]) for event in received],
            [("BTC/USD", "crypto"), ("EUR/USD", "forex")],
        )

    async def test_level3_sends_token_on_its_own_socket(self) -> None:
        received: list[dict] = []

        async def handler(ws):
            frame = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            self.assertEqual(frame["params"]["channel"], "level3")
            self.assertEqual(frame["params"]["token"], "l3-token")
            self.assertEqual(frame["params"]["depth"], 10)
            self.assertNotIn("token", frame)
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "success": True,
                        "result": {"channel": "level3", "symbol": "EUR/USD", "depth": 10},
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "channel": "level3",
                        "type": "snapshot",
                        "data": [
                            {
                                "symbol": "EUR/USD",
                                "checksum": 1,
                                "bids": [
                                    {"order_id": "B1", "limit_price": 1.1, "order_qty": 5},
                                ],
                                "asks": [
                                    {"order_id": "A1", "limit_price": 1.2, "order_qty": 2},
                                ],
                            }
                        ],
                    }
                )
            )
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            consumer = MarketDataConsumer(
                ["EUR/USD"],
                ["level3"],
                l3_url=f"ws://127.0.0.1:{port}",
                token_factory=lambda: "l3-token",
                l3_depth=10,
            )
            count = await consumer.run(received.append, asyncio.Event(), max_messages=1)

        self.assertEqual(count, 1)
        self.assertEqual(received[0]["channel"], "level3")
        self.assertEqual(received[0]["asset_class"], "forex")
        self.assertEqual(received[0]["bids"][0]["order_id"], "B1")


if __name__ == "__main__":
    unittest.main()
