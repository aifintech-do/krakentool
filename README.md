# krakentool

Public market-data consumer for the Kraken Spot WebSocket API v2. One connection carries crypto and forex (`BTC/USD` and `EUR/USD` use the same feed).

## Introduction

Kraken Spot is a base for market-data tools and for a trading application. Public ticker, trades, book, and candles need no account. Your fills, the level 3 book, and later order entry (`add_order`, `amend_order`, `cancel_order`) use an API key. krakentool covers the market-data, account, and backtest layers. The full write-up, including how to create a key and the documentation links, is in [Introduction](docs/FEATURES.md#introduction).

Create a key in Kraken Pro under **Settings → API → Create API key**. Turn on **Access WebSockets API**. The public value is `KRAKEN_API_KEY`. The private value, shown once, is `KRAKEN_API_SECRET`. Leave **Withdraw Funds** off unless that key must move funds.

- [How to create an API key on Kraken Pro](https://support.kraken.com/articles/how-to-create-an-api-key-on-kraken-pro)
- [API key permissions](https://docs.kraken.com/exchange/guides/rest/api-keys)
- [Spot REST authentication](https://docs.kraken.com/exchange/guides/rest/authentication)
- [Spot WebSocket API v2](https://docs.kraken.com/exchange/api-reference/spot-websocket)
- [WebSocket authentication](https://docs.kraken.com/exchange/guides/websockets/authentication)

Feature overview and diagrams: [docs/FEATURES.md](docs/FEATURES.md). Sample commands: [docs/FEATURES.md](docs/FEATURES.md#sample-commands).

## Get started

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/). Dependencies are declared in `pyproject.toml` and pinned in `uv.lock` (`websockets` 15.0.1). Install from that lockfile:

```bash
uv sync
uv run krakentool BTC/USD EUR/USD --channels ticker,trade --duration 10
```

`uv sync` creates `.venv` and installs the `krakentool` command into it. Public channels need no API key. Level 3 and `history` read `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`, or the key stored by `kraken auth login`. `dataset` calls the `kraken` CLI, which must already be on `PATH`.

Quotes are published on best-bid/offer changes so quiet forex books still update.

```bash
uv run krakentool
uv run krakentool BTC/USD ETH/USD EUR/USD GBP/USD --channels ticker,trade --format text
uv run krakentool EUR/USD USD/JPY --duration 10
```

Stdout is newline-delimited JSON. Each market event includes `channel`, `type` (`snapshot` or `update`), `asset_class` (`crypto` or `forex`), and the venue fields. Connection status, subscription acks, and errors go to stderr. The process reconnects with backoff and resubscribes after a dropped socket. `Ctrl-C` stops it.

Channels: `ticker` (default), `trade`, `book`, `ohlc`, and `level3`. Public channels use `wss://ws.kraken.com/v2`. `level3` is the authenticated per-order book on `wss://ws-l3.kraken.com/v2` (depth 10, 100, or 1000) and uses the same credentials as `history`. It cannot share that socket with the public book, so requesting both opens two connections.

```bash
uv run krakentool BTC/USD EUR/USD --channels level3 --l3-depth 10 --duration 10
```

Your own fills and orders use the authenticated executions WebSocket (`wss://ws-auth.kraken.com/v2`). Credentials come from `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` or from `kraken auth login`. The snapshot is open orders plus the latest 50 fills; older closed orders are not replayed.

```bash
uv run krakentool history
uv run krakentool history --format text
uv run krakentool history BTC/USD --trades
uv run krakentool history --follow
```

Each record is `own_trade` or `own_order` with `"source": "websocket"`.

## Backtesting dataset

Daily candles are paged with the `last` cursor from each OHLC response. Minute candles and trade ticks are optional and share a drill-down window. Tick VWAP, volume, and trade count are checked against every candle that sits fully inside that window. Kraken returns at most 720 OHLC points per interval, so use daily bars for the long view and minute bars only for the stretch you need.

Flow and sequence figures: [docs/FEATURES.md](docs/FEATURES.md#backtesting-dataset).

Missing candles are recorded in `gaps.json`. `--gaps exclude` leaves them out. `--gaps forward-fill` inserts a flat bar at the previous close with zero volume.

```bash
uv run krakentool dataset BTC/USD EUR/USD \
  --start 2026-10-29 --end 2026-10-31 \
  --drill-start 2026-10-31T21:00:00Z --drill-end 2026-10-31T21:20:00Z \
  --minutes --ticks --gaps exclude --out dataset
```

`--start` and `--drill-start` accept `YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SSZ`, or unix seconds. Minute history only goes back about 12 hours (720 one-minute candles), so keep the drill window inside that.

## License

krakentool is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the [GNU General Public License](LICENSE) for details.

Copyright (C) 2026 aifintech-do. `krakentool --version` prints the short notice. The `websockets` dependency stays under the BSD 3-Clause license that ships with that package.
