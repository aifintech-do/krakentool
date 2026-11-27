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

"""Publish krakentool events to a kdb+ tickerplant.

The tickerplant evaluates ``.kt.ingest`` on one JSON object. PyKX is used when
it is installed. Otherwise the same call is sent with the kdb IPC protocol.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from pathlib import Path
from typing import Any

from krakentool import __file__ as _pkg_file


class QError(RuntimeError):
    """The kdb+ process could not be reached or rejected the session."""


def q_script_dir() -> Path:
    """Directory of the q scripts, whether this is a checkout or an installed wheel."""
    bundled = Path(_pkg_file).resolve().parent / "kdb"
    if (bundled / "tick.q").is_file():
        return bundled
    return Path(_pkg_file).resolve().parent.parent / "kdb"


def parse_q_address(value: str) -> tuple[str, int]:
    """Split ``host:port``. An address without a port uses 5010."""
    text = value.strip()
    if not text:
        raise QError("q address is empty")
    host, sep, port_text = text.rpartition(":")
    if not sep:
        return text, 5010
    if not host:
        raise QError(f"q address {value!r} is missing a host")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise QError(f"q address {value!r} has a non-numeric port") from exc
    if port <= 0 or port > 65535:
        raise QError(f"q port {port} is out of range")
    return host, port


def q_escape(text: str) -> str:
    """Escape a string so it can sit inside a q double-quoted literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def ingest_expression(event: dict[str, Any]) -> str:
    """q expression that ingests one event."""
    raw = json.dumps(event, separators=(",", ":"), default=str)
    return '.kt.ingest "' + q_escape(raw) + '"'


def q_char_message(expression: str, *, sync: bool = False) -> bytes:
    """One little-endian IPC message whose data is a character vector.

    kdb+ evaluates a character-vector message. Async messages do not require
    a reply, which is what a market-data publisher wants.
    """
    payload = expression.encode("utf-8")
    body = bytes((0x0A, 0x00)) + struct.pack("<i", len(payload)) + payload
    header = bytes((0x01, 0x01 if sync else 0x00, 0x00, 0x00)) + struct.pack("<i", 8 + len(body))
    return header + body


class QPublisher:
    """Hold one connection to a tickerplant and send ``.kt.ingest``."""

    def __init__(self, address: str, *, backend: str = "auto", timeout: float = 5.0) -> None:
        self.host, self.port = parse_q_address(address)
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._pykx: Any = None
        choice = backend
        if choice == "auto":
            choice = "pykx" if os.environ.get("KRAKENTOOL_PYKX") == "1" else "ipc"
        if choice == "pykx":
            self._pykx = _pykx_connection(self.host, self.port)
        elif choice == "ipc":
            self._connect()
        else:
            raise QError(f"unknown q backend {backend!r}")

    def publish(self, event: dict[str, Any]) -> None:
        expression = ingest_expression(event)
        if self._pykx is not None:
            self._pykx(".kt.ingest", json.dumps(event, separators=(",", ":"), default=str))
            return
        try:
            self._send(expression)
        except OSError:
            self.close()
            self._connect()
            self._send(expression)

    def close(self) -> None:
        sock = self._socket
        self._socket = None
        if sock is not None:
            sock.close()
        closer = getattr(self._pykx, "close", None)
        if closer is not None:
            closer()
            self._pykx = None

    def _connect(self) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        sock.sendall(b"\x00")
        accepted = sock.recv(1)
        if not accepted:
            sock.close()
            raise QError(f"kdb+ at {self.host}:{self.port} rejected the session")
        self._socket = sock

    def _send(self, expression: str) -> None:
        if self._socket is None:
            raise QError("q publisher is not connected")
        self._socket.sendall(q_char_message(expression))


def _pykx_connection(host: str, port: int) -> Any:
    try:
        import pykx
    except ImportError as exc:
        raise QError("KRAKENTOOL_PYKX=1 but pykx is not installed") from exc
    for name in ("SyncQConnection", "QConnection"):
        ctor = getattr(pykx, name, None)
        if ctor is None:
            continue
        try:
            return ctor(host=host, port=port)
        except TypeError:
            return ctor(host, port)
    raise QError("pykx is installed but has no QConnection")
