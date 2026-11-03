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

"""Classify v2 symbols into crypto and forex.

Spot WebSocket v2 uses one public endpoint and one symbol format (`BASE/QUOTE`)
for both books. Forex is a pair whose base and quote are both fiat currencies.
Stablecoins such as USDT, USDC, and EURC are not fiat, so `BTC/USD` and
`USDT/EUR` stay crypto while `EUR/USD` is forex.
"""

from __future__ import annotations

import re

# ISO 4217 codes Kraken uses (or may use) as cash legs on the forex book.
# Deliberately excludes tokenized cash (USDT, USDC, EURC, PYUSD, DAI, ...).
FIAT = frozenset(
    {
        "AED",
        "AUD",
        "BHD",
        "BRL",
        "CAD",
        "CHF",
        "CNH",
        "CNY",
        "CZK",
        "DKK",
        "EUR",
        "GBP",
        "HKD",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "JPY",
        "KRW",
        "KWD",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "OMR",
        "PHP",
        "PLN",
        "QAR",
        "RON",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TRY",
        "TWD",
        "USD",
        "VND",
        "ZAR",
    }
)

_SYMBOL = re.compile(r"^[A-Z0-9]{1,16}/[A-Z0-9]{1,16}$")


def parse_symbol(symbol: str) -> tuple[str, str]:
    text = symbol.strip().upper()
    if not _SYMBOL.fullmatch(text):
        raise ValueError(
            f"invalid symbol {symbol!r}; expected BASE/QUOTE such as BTC/USD or EUR/USD"
        )
    base, quote = text.split("/", 1)
    return base, quote


def asset_class(symbol: str) -> str:
    """Return `forex` when both legs are fiat, otherwise `crypto`."""
    base, quote = parse_symbol(symbol)
    if base in FIAT and quote in FIAT:
        return "forex"
    return "crypto"
