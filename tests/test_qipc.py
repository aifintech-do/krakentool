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

"""Tests for the kdb IPC publisher."""

from __future__ import annotations

import json
import socket
import struct
import threading
import unittest

from krakentool.qipc import QError, QPublisher, ingest_expression, parse_q_address, q_char_message, q_escape, q_script_dir


class FramingTest(unittest.TestCase):
    def test_address_defaults_the_tickerplant_port(self) -> None:
        self.assertEqual(parse_q_address("localhost"), ("localhost", 5010))
        self.assertEqual(parse_q_address("127.0.0.1:5011"), ("127.0.0.1", 5011))

    def test_bad_address_raises(self) -> None:
        with self.assertRaises(QError):
            parse_q_address(":5010")
        with self.assertRaises(QError):
            parse_q_address("localhost:nope")

    def test_escape_round_trips_quotes_and_slashes(self) -> None:
        raw = json.dumps({"s": 'a"b\\c'}, separators=(",", ":"))
        escaped = q_escape(raw)
        restored = []
        index = 0
        while index < len(escaped):
            if escaped[index] == "\\" and index + 1 < len(escaped):
                restored.append(escaped[index + 1])
                index += 2
            else:
                restored.append(escaped[index])
                index += 1
        self.assertEqual("".join(restored), raw)
        self.assertIn('.kt.ingest "', ingest_expression({"channel": "ticker", "symbol": "BTC/USD"}))

    def test_message_is_a_little_endian_char_vector(self) -> None:
        message = q_char_message('.kt.ingest "[]"', sync=False)
        self.assertEqual(message[0], 1)
        self.assertEqual(message[1], 0)
        self.assertEqual(struct.unpack_from("<i", message, 4)[0], len(message))
        self.assertEqual(message[8], 0x0A)
        count = struct.unpack_from("<i", message, 10)[0]
        self.assertEqual(message[14 : 14 + count], b'.kt.ingest "[]"')

    def test_script_dir_contains_the_tickerplant(self) -> None:
        self.assertTrue((q_script_dir() / "tick.q").is_file())
        self.assertTrue((q_script_dir() / "hdb.q").is_file())


class PublishTest(unittest.TestCase):
    def test_publish_handshakes_and_sends_ingest(self) -> None:
        received: list[bytes] = []
        ready = threading.Event()

        def serve() -> None:
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            port = server.getsockname()[1]
            serve.port = port
            ready.set()
            conn, _ = server.accept()
            hello = conn.recv(1)
            self.assertEqual(hello, b"\x00")
            conn.sendall(bytes((3,)))
            chunks = b""
            while len(chunks) < 8:
                chunks += conn.recv(8 - len(chunks))
            total = struct.unpack_from("<i", chunks, 4)[0]
            while len(chunks) < total:
                chunks += conn.recv(total - len(chunks))
            received.append(chunks)
            conn.close()
            server.close()

        thread = threading.Thread(target=serve)
        thread.start()
        self.assertTrue(ready.wait(2))
        publisher = QPublisher(f"127.0.0.1:{serve.port}", backend="ipc", timeout=2)
        publisher.publish({"channel": "ticker", "symbol": "EUR/USD", "bid": 1.1})
        thread.join(2)
        publisher.close()
        self.assertEqual(len(received), 1)
        body = received[0][14:]
        self.assertIn(b".kt.ingest", body)
        self.assertIn(b"EUR/USD", body)


if __name__ == "__main__":
    unittest.main()
