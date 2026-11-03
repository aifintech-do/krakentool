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

"""Long-lived public market-data session with resubscribe on reconnect."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from krakentool.protocol import (
    L3_WS_URL,
    PUBLIC_WS_URL,
    build_subscriptions,
    control_summary,
    market_events,
    ping,
)

TokenFactory = Callable[[], str]

log = logging.getLogger("krakentool")

Emit = Callable[[dict[str, Any]], None]


class SubscribeError(RuntimeError):
    """The venue rejected one or more subscriptions and strict mode is on."""


class MarketDataConsumer:
    def __init__(
        self,
        symbols: list[str],
        channels: list[str],
        *,
        url: str = PUBLIC_WS_URL,
        snapshot: bool = True,
        event_trigger: str = "bbo",
        book_depth: int = 10,
        l3_depth: int = 10,
        l3_url: str = L3_WS_URL,
        token_factory: TokenFactory | None = None,
        ohlc_interval: int = 1,
        ping_interval: float = 30.0,
        strict: bool = False,
    ) -> None:
        self.symbols = symbols
        self.channels = channels
        self.public_channels = [name for name in channels if name != "level3"]
        self.level3 = "level3" in channels
        self.url = url
        self.l3_url = l3_url
        self.snapshot = snapshot
        self.event_trigger = event_trigger
        self.book_depth = book_depth
        self.l3_depth = l3_depth
        self.ohlc_interval = ohlc_interval
        self.ping_interval = ping_interval
        self.strict = strict
        self.token_factory = token_factory
        if self.level3 and token_factory is None:
            raise ValueError("level3 requires credentials; sign in with `kraken auth login`")
        self.frames = (
            build_subscriptions(
                symbols,
                self.public_channels,
                snapshot=snapshot,
                event_trigger=event_trigger,
                book_depth=book_depth,
                ohlc_interval=ohlc_interval,
            )
            if self.public_channels
            else []
        )
        if self.level3:
            # Validate depth now. The token is minted at connect time so a
            # reconnect does not reuse an expired one.
            build_subscriptions(
                symbols,
                ["level3"],
                snapshot=snapshot,
                l3_depth=l3_depth,
                token="validate-only",
            )

    async def run(
        self,
        emit: Emit,
        stop: asyncio.Event,
        *,
        duration: float | None = None,
        max_messages: int | None = None,
    ) -> int:
        """Stream until `stop`, `duration` seconds, or `max_messages` market events.

        Returns the number of market events emitted. A dropped socket reconnects
        with exponential backoff and sends the same subscriptions again.
        """
        if self.public_channels and self.level3:
            return await self._run_pair(emit, stop, duration=duration, max_messages=max_messages)
        if self.level3:
            return await self._reconnect(
                emit,
                stop,
                url=self.l3_url,
                frames_for=self._l3_frames,
                channels=["level3"],
                duration=duration,
                max_messages=max_messages,
            )
        return await self._reconnect(
            emit,
            stop,
            url=self.url,
            frames_for=lambda: self.frames,
            channels=self.public_channels,
            duration=duration,
            max_messages=max_messages,
        )

    async def _run_pair(
        self,
        emit: Emit,
        stop: asyncio.Event,
        *,
        duration: float | None,
        max_messages: int | None,
    ) -> int:
        """Public book and level3 use different sockets. Share one event budget."""
        state = {"n": 0}

        def gated(event: dict[str, Any]) -> None:
            if max_messages is not None and state["n"] >= max_messages:
                stop.set()
                return
            emit(event)
            state["n"] += 1
            if max_messages is not None and state["n"] >= max_messages:
                stop.set()

        public = asyncio.create_task(
            self._reconnect(
                gated,
                stop,
                url=self.url,
                frames_for=lambda: self.frames,
                channels=self.public_channels,
                duration=duration,
                max_messages=None,
            )
        )
        level3 = asyncio.create_task(
            self._reconnect(
                gated,
                stop,
                url=self.l3_url,
                frames_for=self._l3_frames,
                channels=["level3"],
                duration=duration,
                max_messages=None,
            )
        )
        try:
            await asyncio.wait({public, level3}, return_when=asyncio.FIRST_EXCEPTION)
        finally:
            stop.set()
            for task in (public, level3):
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(public, level3, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                raise result
        return state["n"]

    def _l3_frames(self) -> list[dict[str, Any]]:
        assert self.token_factory is not None
        token = self.token_factory()
        return build_subscriptions(
            self.symbols,
            ["level3"],
            snapshot=self.snapshot,
            book_depth=self.book_depth,
            l3_depth=self.l3_depth,
            ohlc_interval=self.ohlc_interval,
            token=token,
        )

    async def _reconnect(
        self,
        emit: Emit,
        stop: asyncio.Event,
        *,
        url: str,
        frames_for: Callable[[], list[dict[str, Any]]],
        channels: list[str],
        duration: float | None,
        max_messages: int | None,
    ) -> int:
        deadline = None if duration is None else time.monotonic() + duration
        emitted = 0
        backoff = 1.0
        while not stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                frames = await asyncio.to_thread(frames_for)
                count, reason = await self._session(
                    emit,
                    stop,
                    url=url,
                    frames=frames,
                    channels=channels,
                    deadline=deadline,
                    max_messages=None if max_messages is None else max_messages - emitted,
                )
            except asyncio.CancelledError:
                raise
            except SubscribeError:
                raise
            except (ConnectionClosed, OSError, TimeoutError) as exc:
                if stop.is_set() or _deadline_reached(deadline):
                    break
                log.warning("connection lost (%s); retrying in %.0fs", exc, backoff)
                if not await _wait(stop, backoff, deadline):
                    break
                backoff = min(backoff * 2, 30.0)
                continue

            emitted += count
            if reason in {"deadline", "stopped", "limited"}:
                break
            if stop.is_set() or _deadline_reached(deadline):
                break
            log.warning("socket closed; reconnecting in %.0fs", backoff)
            if not await _wait(stop, backoff, deadline):
                break
            backoff = min(backoff * 2, 30.0)
        return emitted

    async def _session(
        self,
        emit: Emit,
        stop: asyncio.Event,
        *,
        url: str,
        frames: list[dict[str, Any]],
        channels: list[str],
        deadline: float | None,
        max_messages: int | None,
    ) -> tuple[int, str]:
        if max_messages is not None and max_messages <= 0:
            return 0, "limited"
        emitted = 0
        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
            open_timeout=10,
        ) as ws:
            log.info(
                "connected %s symbols=%d channels=%s",
                url,
                len(self.symbols),
                ",".join(channels),
            )
            for frame in frames:
                await ws.send(json.dumps(frame))

            expected_acks = len(self.symbols) * len(channels)
            acks = 0
            failures: list[str] = []
            ping_task = asyncio.create_task(self._ping(ws, stop), name="kraken-ping")
            try:
                while not stop.is_set():
                    timeout = None if deadline is None else deadline - time.monotonic()
                    if timeout is not None and timeout <= 0:
                        return emitted, "deadline"
                    raw = await _recv(ws, stop, timeout)
                    if raw is None:
                        return emitted, "stopped" if stop.is_set() else "deadline"
                    message = json.loads(raw)
                    if not isinstance(message, dict):
                        log.debug("ignored non-object frame")
                        continue
                    control = control_summary(message)
                    if control is not None:
                        self._log_control(control)
                        if control["kind"] == "subscribe":
                            acks += 1
                            if control.get("success") is False:
                                failures.append(
                                    f"{control.get('symbol') or control.get('channel')}: "
                                    f"{control.get('error') or 'rejected'}"
                                )
                            if self.strict and acks >= expected_acks and failures:
                                raise SubscribeError(_failure_text(failures, expected_acks))
                        continue
                    for event in market_events(message):
                        emit(event)
                        emitted += 1
                        if max_messages is not None and emitted >= max_messages:
                            return emitted, "limited"
            finally:
                ping_task.cancel()
                await asyncio.gather(ping_task, return_exceptions=True)
        return emitted, "closed"

    async def _ping(self, ws: Any, stop: asyncio.Event) -> None:
        req_id = 10_000
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.ping_interval)
                return
            except asyncio.TimeoutError:
                pass
            req_id += 1
            await ws.send(json.dumps(ping(req_id)))

    @staticmethod
    def _log_control(control: dict[str, Any]) -> None:
        kind = control["kind"]
        if kind == "heartbeat":
            log.debug("heartbeat")
            return
        if kind == "status":
            log.info(
                "status system=%s api=%s version=%s",
                control.get("system"),
                control.get("api_version"),
                control.get("version"),
            )
            return
        if kind == "pong":
            log.debug("pong req_id=%s", control.get("req_id"))
            return
        if control.get("success") is False:
            log.error(
                "%s failed channel=%s symbol=%s error=%s",
                kind,
                control.get("channel"),
                control.get("symbol"),
                control.get("error"),
            )
            return
        if kind == "subscribe":
            log.info(
                "subscribed channel=%s symbol=%s",
                control.get("channel"),
                control.get("symbol"),
            )


def _failure_text(failures: list[str], expected: int) -> str:
    detail = "; ".join(failures[:8])
    return f"{len(failures)} of {expected} subscriptions failed: {detail}"


def _deadline_reached(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


async def _wait(stop: asyncio.Event, seconds: float, deadline: float | None) -> bool:
    """Sleep up to `seconds`, stopping early on `stop` or `deadline`.

    Returns True when the wait finished and the caller should continue.
    """
    if deadline is not None:
        seconds = min(seconds, max(0.0, deadline - time.monotonic()))
    if seconds <= 0:
        return False
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
        return False
    except asyncio.TimeoutError:
        return not _deadline_reached(deadline)


async def _recv(ws: Any, stop: asyncio.Event, timeout: float | None) -> str | bytes | None:
    """Next text frame, or None when `stop` is set or `timeout` elapses."""
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
