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

"""Spot API credentials and the WebSocket token they mint.

Resolution order matches the Kraken CLI: environment variables, then
`~/.config/kraken/config.toml`. The secret is used only to sign
`GetWebSocketsToken` and is never included in errors or logs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Mapping

from krakentool.protocol import REST_URL

TOKEN_PATH = "/0/private/GetWebSocketsToken"


class CredentialsError(RuntimeError):
    """No usable Spot API key, or Kraken rejected the token request."""


def load_credentials(
    environ: Mapping[str, str] | None = None,
    *,
    config_text: str | None = None,
    config_path: Path | None = None,
) -> tuple[str, str]:
    env = os.environ if environ is None else environ
    key = (env.get("KRAKEN_API_KEY") or "").strip()
    secret = (env.get("KRAKEN_API_SECRET") or "").strip()
    if key and secret:
        return key, secret
    text = config_text
    if text is None:
        path = config_path or _default_config_path()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CredentialsError(
                "Set KRAKEN_API_KEY and KRAKEN_API_SECRET, or sign in with `kraken auth login`."
            ) from exc
    found = _pairs_from_toml(text)
    if not found:
        raise CredentialsError(
            "No Spot API key in the Kraken CLI config. "
            "Set KRAKEN_API_KEY and KRAKEN_API_SECRET, or run `kraken auth login`."
        )
    active = _active_name(text)
    if active:
        for name, pair in found:
            leaf = name.rsplit(".", 1)[-1]
            if name == active or leaf == active or leaf.replace("-", "_") == active.replace("-", "_"):
                return pair
    for name, pair in found:
        if name == "auth" or name.endswith(".auth"):
            return pair
    if len(found) == 1:
        return found[0][1]
    raise CredentialsError(
        "Several Spot keys are stored. Set KRAKEN_API_KEY and KRAKEN_API_SECRET to choose one."
    )


def fetch_websocket_token(
    api_key: str,
    api_secret: str,
    *,
    rest_url: str = REST_URL,
    opener: urllib.request.OpenerDirector | None = None,
    nonce: str | None = None,
) -> str:
    """Mint a short-lived private-channel token. Do not log the return value.

    The nonce is nanoseconds, matching the Kraken CLI. A millisecond nonce is
    rejected once any nanosecond nonce has been used for the same key.
    """
    try:
        return _fetch_websocket_token(
            api_key,
            api_secret,
            rest_url=rest_url,
            opener=opener,
            nonce=nonce or str(time.time_ns()),
        )
    except CredentialsError as exc:
        if nonce is not None or "Invalid nonce" not in str(exc):
            raise
        time.sleep(0.01)
        return _fetch_websocket_token(
            api_key,
            api_secret,
            rest_url=rest_url,
            opener=opener,
            nonce=str(time.time_ns()),
        )


def _fetch_websocket_token(
    api_key: str,
    api_secret: str,
    *,
    rest_url: str,
    opener: urllib.request.OpenerDirector | None,
    nonce: str,
) -> str:
    body = {"nonce": nonce}
    encoded = urllib.parse.urlencode(body)
    signature = sign(TOKEN_PATH, body, api_secret)
    request = urllib.request.Request(
        rest_url.rstrip("/") + TOKEN_PATH,
        data=encoded.encode(),
        method="POST",
        headers={
            "API-Key": api_key,
            "API-Sign": signature,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "krakentool",
        },
    )
    open_url = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_url(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise CredentialsError(f"GetWebSocketsToken failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise CredentialsError(f"GetWebSocketsToken failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise CredentialsError("GetWebSocketsToken returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CredentialsError("GetWebSocketsToken returned an unexpected payload")
    errors = payload.get("error")
    if isinstance(errors, list) and errors:
        raise CredentialsError("GetWebSocketsToken rejected the key: " + "; ".join(str(item) for item in errors))
    result = payload.get("result")
    token = result.get("token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise CredentialsError("GetWebSocketsToken did not return a token")
    return token


def sign(url_path: str, data: dict[str, str], secret: str) -> str:
    encoded = (data["nonce"] + urllib.parse.urlencode(data)).encode()
    message = url_path.encode() + hashlib.sha256(encoded).digest()
    try:
        secret_bytes = base64.b64decode(secret, validate=True)
    except Exception as exc:
        raise CredentialsError("API secret is not valid base64") from exc
    mac = hmac.new(secret_bytes, message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _default_config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    root = Path(xdg) if xdg else Path.home() / ".config"
    return root / "kraken" / "config.toml"


def _pairs_from_toml(text: str) -> list[tuple[str, tuple[str, str]]]:
    tables = _tables(text)
    pairs: list[tuple[str, tuple[str, str]]] = []
    for name, fields in tables.items():
        key = fields.get("api_key") or fields.get("key")
        secret = fields.get("api_secret") or fields.get("secret") or fields.get("private_key")
        if key and secret:
            pairs.append((name, (key, secret)))
    return pairs


def _active_name(text: str) -> str | None:
    tables = _tables(text)
    for name in ("", "auth", "settings"):
        active = tables.get(name, {}).get("active")
        if active:
            return active
    return None


def _tables(text: str) -> dict[str, dict[str, str]]:
    tables: dict[str, dict[str, str]] = {"": {}}
    current = ""
    for raw in text.splitlines():
        line = _strip_comment(raw).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]") and not line.startswith("[["):
            current = line[1:-1].strip().strip('"').strip("'")
            tables.setdefault(current, {})
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        tables.setdefault(current, {})[key.strip()] = _unquote(value.strip())
    return tables


def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for char in line:
        if quote:
            out.append(char)
            if char == quote:
                quote = None
            continue
        if char in {'"', "'"}:
            quote = char
            out.append(char)
            continue
        if char == "#":
            break
        out.append(char)
    return "".join(out)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        body = value[1:-1]
        return body.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
    return value
