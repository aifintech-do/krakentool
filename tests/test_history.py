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
from io import BytesIO
from urllib.request import Request

import websockets

from krakentool.credentials import CredentialsError, fetch_websocket_token, load_credentials
from krakentool.history import (
    HistoryError,
    execution_events,
    executions_subscribe,
    stream_executions,
    to_v2_symbol,
)


class SymbolTranslationTests(unittest.TestCase):
    def test_rest_names_become_v2_symbols(self) -> None:
        self.assertEqual(to_v2_symbol("XXBTZUSD"), "BTC/USD")
        self.assertEqual(to_v2_symbol("XBTUSD"), "BTC/USD")
        self.assertEqual(to_v2_symbol("XDGUSD"), "XDG/USD")
        self.assertEqual(to_v2_symbol("ZEURZUSD"), "EUR/USD")
        self.assertEqual(to_v2_symbol("EURUSD"), "EUR/USD")
        self.assertEqual(to_v2_symbol("btc/usd"), "BTC/USD")

    def test_unknown_concatenated_pair_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            to_v2_symbol("NOTAPA")


class CredentialTests(unittest.TestCase):
    def test_environment_wins(self) -> None:
        key, secret = load_credentials(
            {"KRAKEN_API_KEY": "key-env", "KRAKEN_API_SECRET": "c2VjcmV0"},
            config_text='[auth]\napi_key = "key-file"\napi_secret = "ZmlsZQ=="\n',
        )
        self.assertEqual((key, secret), ("key-env", "c2VjcmV0"))

    def test_active_signin_table(self) -> None:
        text = """
active = "sign-in"
[auth]
api_key = "from-auth"
api_secret = "YXV0aA=="
[sign-in]
api_key = "from-login"
api_secret = "bG9naW4="
"""
        key, secret = load_credentials({}, config_text=text)
        self.assertEqual(key, "from-login")
        self.assertEqual(secret, "bG9naW4=")

    def test_missing_key_raises_without_file_contents(self) -> None:
        with self.assertRaises(CredentialsError) as caught:
            load_credentials({}, config_text="[settings]\noutput = \"json\"\n")
        self.assertNotIn("json", str(caught.exception).lower())


class TokenTests(unittest.TestCase):
    def test_token_request_is_signed_and_secret_stays_out_of_the_body(self) -> None:
        seen: dict[str, Request] = {}

        class Response(BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class Opener:
            def open(self, request, timeout=0):
                seen["request"] = request
                return Response(b'{"error":[],"result":{"token":"ws-token"}}')

        token = fetch_websocket_token(
            "api-key",
            "c2VjcmV0LXNlY3JldA==",
            opener=Opener(),
            nonce="1000",
        )
        self.assertEqual(token, "ws-token")
        request = seen["request"]
        body = request.data.decode()
        self.assertIn("nonce=1000", body)
        self.assertNotIn("c2VjcmV0", body)
        self.assertEqual(request.get_header("Api-key"), "api-key")
        self.assertTrue(request.get_header("Api-sign"))
        self.assertTrue(request.full_url.endswith("/0/private/GetWebSocketsToken"))


class ExecutionParseTests(unittest.TestCase):
    def test_trade_and_order_snapshot(self) -> None:
        events = execution_events(
            {
                "channel": "executions",
                "type": "snapshot",
                "data": [
                    {
                        "exec_type": "trade",
                        "exec_id": "T-1",
                        "trade_id": 7,
                        "order_id": "O-1",
                        "symbol": "BTC/USD",
                        "side": "buy",
                        "order_type": "limit",
                        "last_qty": 0.1,
                        "last_price": 20000,
                        "cost": 2000,
                        "liquidity_ind": "m",
                        "timestamp": "2022-06-13T00:00:00.000000Z",
                        "fees": [{"asset": "USD", "qty": 0.5}],
                    },
                    {
                        "exec_type": "new",
                        "order_id": "O-2",
                        "symbol": "EUR/USD",
                        "side": "sell",
                        "order_type": "limit",
                        "order_status": "new",
                        "order_qty": 1000,
                        "cum_qty": 0,
                        "limit_price": 1.1,
                        "timestamp": "2026-01-01T00:00:00.000000Z",
                    },
                ],
            }
        )
        self.assertEqual(events[0]["kind"], "own_trade")
        self.assertEqual(events[0]["asset_class"], "crypto")
        self.assertEqual(events[0]["source"], "websocket")
        self.assertTrue(events[0]["maker"])
        self.assertEqual(events[0]["fee"], 0.5)
        self.assertEqual(events[1]["kind"], "own_order")
        self.assertEqual(events[1]["asset_class"], "forex")
        self.assertEqual(events[1]["status"], "new")

    def test_subscribe_frame_carries_the_token_only_in_params(self) -> None:
        frame = executions_subscribe(token="secret-token", snap_orders=True, snap_trades=True)
        self.assertEqual(frame["params"]["channel"], "executions")
        self.assertEqual(frame["params"]["token"], "secret-token")
        self.assertTrue(frame["params"]["snap_trades"])
        self.assertNotIn("token", frame)


class LocalExecutionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_snapshot_then_stop(self) -> None:
        received: list[dict] = []

        async def handler(ws):
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            frame = json.loads(raw)
            self.assertEqual(frame["params"]["token"], "test-token")
            self.assertEqual(frame["params"]["channel"], "executions")
            await ws.send(
                json.dumps(
                    {
                        "method": "subscribe",
                        "success": True,
                        "result": {"channel": "executions", "snap_orders": True, "snap_trades": True},
                    }
                )
            )
            await ws.send(json.dumps({"channel": "heartbeat"}))
            await ws.send(
                json.dumps(
                    {
                        "channel": "executions",
                        "type": "snapshot",
                        "data": [
                            {
                                "exec_type": "trade",
                                "exec_id": "T-1",
                                "order_id": "O-1",
                                "symbol": "XBT/USD",
                                "side": "buy",
                                "last_qty": 1,
                                "last_price": 10,
                                "liquidity_ind": "t",
                                "timestamp": "2024-01-01T00:00:00.000000Z",
                            },
                            {
                                "exec_type": "status",
                                "order_id": "O-2",
                                "symbol": "EUR/USD",
                                "side": "buy",
                                "order_status": "new",
                                "order_qty": 5,
                                "timestamp": "2024-01-01T00:00:01.000000Z",
                            },
                        ],
                    }
                )
            )
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            count = await stream_executions(
                received.append,
                asyncio.Event(),
                token="test-token",
                url=f"ws://127.0.0.1:{port}",
                symbols={"BTC/USD", "EUR/USD"},
                follow=False,
                quiet_after=0.2,
            )

        self.assertEqual(count, 2)
        self.assertEqual(received[0]["symbol"], "BTC/USD")
        self.assertEqual(received[0]["kind"], "own_trade")
        self.assertEqual(received[1]["asset_class"], "forex")

    async def test_rejected_subscribe_raises(self) -> None:
        async def handler(ws):
            await ws.recv()
            await ws.send(
                json.dumps(
                    {"method": "subscribe", "success": False, "error": "Invalid session"}
                )
            )
            await ws.wait_closed()

        async with websockets.serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with self.assertRaises(HistoryError):
                await stream_executions(
                    lambda _event: None,
                    asyncio.Event(),
                    token="nope",
                    url=f"ws://127.0.0.1:{port}",
                    quiet_after=0.2,
                )
