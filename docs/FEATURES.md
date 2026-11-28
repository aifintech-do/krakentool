# krakentool

## Introduction

[Kraken Spot](https://docs.kraken.com/exchange/api-reference/spot-websocket) is a public market plus an account API, so the same venue can feed a monitor, a research notebook, or a trading application. Public channels publish ticker, trades, the aggregated book, and candles for crypto and forex on one symbol format (`BTC/USD`, `EUR/USD`). Private channels and order entry use an API key. WebSocket API v2 is the current interface: normalised JSON, `BTC/USD` symbols, and both market data and order messages on a persistent connection.

krakentool is a baseline on that API. It follows the live book, records your own fills and open orders, and builds a checked historical dataset you can replay before a strategy sends an order. That same stream can land in kdb+. `--q` publishes each event to a tickerplant, a realtime process keeps the rows, and `kdb/hdb.q` loads the dataset directory as a date-partitioned historical database. `kdb/browser.q` serves either set of tables in a page. A trading application keeps this layer and adds order entry from the same v2 catalog (`add_order`, `amend_order`, `cancel_order`), documented in the [Spot WebSocket reference](https://docs.kraken.com/exchange/api-reference/spot-websocket).

| Layer | What it gives a trading app | In this project |
| --- | --- | --- |
| Public market data | Quotes, prints, level 2 book, candles | `krakentool` on `wss://ws.kraken.com/v2` |
| Your account | Open orders and recent fills, then live updates | `krakentool history` on `wss://ws-auth.kraken.com/v2` |
| Level 3 book | Each resting order, for queue and microstructure work | `--channels level3` on `wss://ws-l3.kraken.com/v2` |
| History | Daily and minute bars, trade ticks, a VWAP check | `krakentool dataset` |
| kdb/q | Live tables for the stream, and a historical database from the dataset | `--q`, `kdb/tick.q`, `kdb/rdb.q`, `kdb/hdb.q` |
| Data browser | Inspect those tables in a page | `kdb/browser.q`, AG Grid Community in `web/` |
| Order entry | Place, amend, and cancel | [Spot WebSocket v2 order methods](https://docs.kraken.com/exchange/api-reference/spot-websocket) |

### API key and secret

Public market data needs no key. Level 3, your executions, and any later order call need a key pair from Kraken Pro.

1. Sign in to Kraken Pro, open the profile menu, and choose **Settings**, then **API**.
2. Choose **Create API key**. The description is the key’s name. Give it a name you will recognise, such as `krakentool`.
3. Turn on **Access WebSockets API** (also shown as the WebSocket interface). That permission is what allows [`GetWebSocketsToken`](https://docs.kraken.com/api-reference/trading/get-websockets-token). Level 3 and `history` both use that token.
4. For a read-only baseline, also turn on **Query Open Orders & Trades**. Leave **Withdraw Funds** off. Turn on **Modify Orders** and **Cancel/Close Orders** when the application places and cancels orders. The full matrix is in [API key permissions](https://docs.kraken.com/exchange/guides/rest/api-keys).
5. Restrict the key to the IP addresses of the machine that will call the API, then choose **Generate key**.

Kraken shows two values. The public key is the API key. The private key is the API secret. The secret is shown once; store both in a password manager. The secret is used only to sign requests. It is never sent on the wire. Signing is HMAC-SHA512 over the nonce, the body, and the path, described in [Spot REST authentication](https://docs.kraken.com/exchange/guides/rest/authentication).

Pass the pair in the environment, or store it with the Kraken CLI (`kraken auth login`). This repository does not contain keys.

```bash
export KRAKEN_API_KEY="the public key"
export KRAKEN_API_SECRET="the private key"
```

krakentool calls `GetWebSocketsToken`, then puts that token in the subscribe message. See [Spot WebSocket authentication](https://docs.kraken.com/exchange/guides/websockets/authentication).

### Kraken documentation

| Topic | Link |
| --- | --- |
| Create an API key | [How to create an API key on Kraken Pro](https://support.kraken.com/articles/how-to-create-an-api-key-on-kraken-pro) |
| Key permissions | [API key permissions](https://docs.kraken.com/exchange/guides/rest/api-keys) |
| REST signing, nonce, `API-Key` and `API-Sign` | [Spot REST authentication](https://docs.kraken.com/exchange/guides/rest/authentication) |
| WebSocket token | [GetWebSocketsToken](https://docs.kraken.com/api-reference/trading/get-websockets-token) and [WebSocket authentication](https://docs.kraken.com/exchange/guides/websockets/authentication) |
| Spot WebSocket v2, including order entry | [Spot WebSocket](https://docs.kraken.com/exchange/api-reference/spot-websocket) |
| Level 3 order book | [level3 channel](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/level3) and [Level 3 market data](https://docs.kraken.com/exchange/guides/general/l3-data) |
| Candles | [OHLC channel](https://docs.kraken.com/exchange/api-reference/spot-websocket-v2/ohlc) |

## Get started

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/). Runtime dependencies are declared in `pyproject.toml` and pinned in [`uv.lock`](../uv.lock). That lockfile is the install list: today it is this package plus `websockets` 15.0.1. `uv sync` creates `.venv` from the lockfile and installs the `krakentool` command into it.

```bash
uv sync
uv run krakentool --help
uv run krakentool BTC/USD EUR/USD --channels ticker,trade --duration 10
```

Public ticker, trades, book, and OHLC need no API key. Level 3 and `history` mint a WebSocket token from `KRAKEN_API_KEY` and `KRAKEN_API_SECRET`, or from the key stored by `kraken auth login`. The `dataset` command shells out to the `kraken` CLI, which is a separate install and must be on `PATH`. The program is licensed under GPL-3.0-or-later; see [License](#license).

More commands are in [Sample commands](#sample-commands).

## Features

| Command | What you get | Transport |
| --- | --- | --- |
| `krakentool` | Live ticker, trades, aggregated book, and OHLC | `wss://ws.kraken.com/v2` |
| `krakentool --channels level3` | Per-order book (add, modify, delete) | `wss://ws-l3.kraken.com/v2` |
| `krakentool history` | Your open orders and latest fills, then live updates with `--follow` | `wss://ws-auth.kraken.com/v2` |
| `krakentool dataset` | Daily OHLC, optional minute bars and trade ticks, VWAP check, gap policy | Public REST, paged on `last` |
| `krakentool --q` | The live stream or `history`, published into kdb+ as each event arrives | IPC to `kdb/tick.q`, or a pipe into `kdb/feed.q` |
| `q kdb/browser.q` | Table list, column types, and the latest rows | WebSocket from the page in `web/` to the same q process |

A pair is `forex` when both legs are fiat (`EUR/USD`, `USD/JPY`). Anything else, including `BTC/USD` and `USDT/USD`, is `crypto`. Every market event carries that tag.

## How a run is shaped

```mermaid
flowchart TD
  cli["krakentool"]
  cli --> stream["Live market data"]
  cli --> history["Your executions"]
  cli --> dataset["Backtest dataset"]

  stream --> pub["Public socket<br/>wss://ws.kraken.com/v2"]
  stream --> l3["Level 3 socket<br/>wss://ws-l3.kraken.com/v2"]
  history --> auth["Private socket<br/>wss://ws-auth.kraken.com/v2"]
  dataset --> rest["Public OHLC and Trades<br/>paged with last"]

  pub --> out["NDJSON on stdout"]
  l3 --> out
  auth --> out
  out --> qpub["--q  .kt.ingest"]
  qpub --> tp["Tickerplant<br/>kdb/tick.q"]
  tp --> rdb["Realtime tables<br/>kdb/rdb.q"]
  rest --> files["dataset/manifest.json<br/>and per-symbol JSONL"]
  files --> hdb["kdb/hdb.q"]
  hdb --> hfiles["Date partitions<br/>ohlcv1d, ohlcv1m, trades"]
  rdb --> browser["Data browser<br/>kdb/browser.q"]
  hfiles --> browser
  browser --> page["AG Grid Community<br/>web/"]

  creds["API key in the environment<br/>or kraken auth login"] --> token["GetWebSocketsToken"]
  token --> l3
  token --> auth
```

Public channels (`ticker`, `trade`, `book`, `ohlc`) share one socket. Level 3 cannot share it, so asking for both opens a second connection. Stdout is one JSON object per line. Connection status stays on stderr. With `--q`, that same object is also published to the tickerplant. The dataset files are a separate load through `kdb/hdb.q`. `kdb/browser.q` reads the realtime tables or the date partitions and draws them with AG Grid Community. The figures in [kdb/q](#kdbq) show both paths.

## Live public market data

Default symbols are `BTC/USD`, `ETH/USD`, `SOL/USD`, `EUR/USD`, `GBP/USD`, and `USD/JPY`. The ticker trigger defaults to `bbo`, so a quote updates when the best bid or offer changes, which matters on quieter forex books.

```mermaid
sequenceDiagram
  actor User
  participant CLI as krakentool
  participant WS as ws.kraken.com/v2

  User->>CLI: krakentool BTC/USD EUR/USD --channels ticker,trade
  CLI->>WS: connect
  WS-->>CLI: status api_version v2
  CLI->>WS: subscribe ticker symbol BTC/USD, EUR/USD event_trigger bbo
  CLI->>WS: subscribe trade symbol BTC/USD, EUR/USD
  WS-->>CLI: subscribe ack per symbol
  WS-->>CLI: ticker snapshot and trade snapshot
  loop until Ctrl-C, duration, or max messages
    WS-->>CLI: ticker or trade update
    CLI-->>User: NDJSON with asset_class crypto or forex
    CLI->>WS: application ping about every 30s
  end
  Note over CLI,WS: On disconnect, backoff and resubscribe
```

`book` is the aggregated level 2 book (depth 10, 25, 100, 500, or 1000). `ohlc` is the candle stream. Heartbeats and subscribe acknowledgements are not written to stdout.

## Level 3 order book

Level 3 shows each resting order: `order_id`, `limit_price`, and `order_qty`. A snapshot is followed by `add`, `modify`, and `delete`. Depth is 10, 100, or 1000 price levels per side. At most 200 symbols fit on one connection.

```mermaid
sequenceDiagram
  actor User
  participant CLI as krakentool
  participant REST as api.kraken.com
  participant L3 as ws-l3.kraken.com/v2

  User->>CLI: --channels level3 BTC/USD EUR/USD --l3-depth 10
  CLI->>REST: POST /0/private/GetWebSocketsToken
  REST-->>CLI: short-lived token
  CLI->>L3: connect
  L3-->>CLI: status api_version v2
  CLI->>L3: subscribe level3 symbol BTC/USD, EUR/USD depth 10 token
  L3-->>CLI: ack per symbol
  L3-->>CLI: snapshot bids and asks plus checksum
  loop live
    L3-->>CLI: update add, modify, or delete
    CLI-->>User: NDJSON channel level3
  end
  Note over CLI,L3: A new token is minted on each reconnect
```

The token is sent only inside the subscribe message. It is not logged.

## Your fills and orders

`history` subscribes to the private `executions` channel. The snapshot is open orders plus the latest 50 fills. Older closed orders are not replayed. `--follow` keeps the socket open for new fills and order updates. Without it, the process prints the snapshot and exits once the burst goes quiet.

```mermaid
sequenceDiagram
  actor User
  participant CLI as krakentool history
  participant REST as api.kraken.com
  participant WS as ws-auth.kraken.com/v2

  User->>CLI: history BTC/USD --follow
  CLI->>REST: POST /0/private/GetWebSocketsToken
  REST-->>CLI: token
  CLI->>WS: connect
  CLI->>WS: subscribe executions snap_orders snap_trades token
  WS-->>CLI: subscribe ack
  WS-->>CLI: snapshot of open orders and recent fills
  CLI-->>User: own_order and own_trade NDJSON
  opt --follow
    WS-->>CLI: execution update
    CLI-->>User: own_trade or own_order
  end
```

A fill (`exec_type` `trade`) becomes `own_trade` with price, size, fee, and whether it was maker. Other execution reports become `own_order`. REST pair names such as `XXBTZUSD` are rewritten to v2 symbols such as `BTC/USD` when they appear.

## Backtesting dataset

`krakentool dataset` builds an offline series for a backtest. It reads public OHLC and public trades through the `kraken` CLI. It does not open a WebSocket, and it does not use an API key.

Daily candles cover the long window. Minute candles and trade ticks are optional and share a shorter drill window. Kraken returns at most 720 OHLC points for one interval, so a minute series only reaches about the last 12 hours. Keep the drill window inside that.

### Flow

![Flow of the backtesting dataset, from the command through daily OHLC, optional minute candles and trade ticks, a gap policy, a tick check, and the files that are written](images/dataset-flow.svg)

One symbol is collected at a time.

1. **Daily OHLC** always runs. The first request sets `--since` to the window start. Each response includes `last`, and the next request passes that value as `--since`. Paging stops when the cursor stalls, the page is empty, or `last` is at or past the end. Candles are kept by open time. A run that hits the page cap is marked truncated in the manifest.
2. **Minute OHLC** runs with `--minutes`, on the drill window, at interval `1`, with the same cursor.
3. **Trade ticks** run with `--ticks`. Each page holds 1000 trades. The trade cursor is in nanoseconds. Rows are kept by `trade_id`. Paging stops once a trade time reaches the drill end, or at 30 pages.
4. **Gap policy** looks for holes between the first and last candle that came back. `--gaps exclude` leaves those bars out and still records the missing open times in `gaps.json`. `--gaps forward-fill` inserts a flat bar at the previous close, with volume 0, count 0, and `gap` set.
5. **Tick check** compares ticks with candles that sit fully inside the drill window. The trade count must match. Volume and VWAP must fall within `--vwap-tolerance` (default `0.0001`) relative error. Forward-filled bars are skipped. A miss means a page was skipped or the candle is incomplete.
6. **Files** land under `--out`: `manifest.json`, plus one directory per symbol (`BTC-USD`, `EUR-USD`).

A forex symbol, both legs fiat, adds `--asset-class forex` on every `kraken` call. `BTC/USD` does not.

### Sequence

![Sequence of a dataset run between you, krakentool, the kraken CLI, and Kraken public REST](images/dataset-sequence.svg)

`krakentool` runs `kraken -o json --log-format compact` and reads one JSON object from stdout. The CLI calls public OHLC or Trades. A pause, 0.25 seconds by default, sits between pages. Daily paging is shown in full. Minute candles and trade ticks use that same `last` loop when those flags are set. After the pages, the process dedupes, applies the gap policy, checks tick VWAP against the candles, and prints the path to `manifest.json`.

### Files

| File | Contents |
| --- | --- |
| `manifest.json` | Candle counts, gap counts, truncated flags, VWAP failures |
| `<symbol>/ohlcv-1d.jsonl` | Daily open, high, low, close, VWAP, volume, trade count |
| `<symbol>/ohlcv-1m.jsonl` | Minute candles, when `--minutes` is set |
| `<symbol>/trades.jsonl` | Price, size, side, trade id |
| `<symbol>/validation.jsonl` | Candle VWAP against tick VWAP, with `ok` |
| `<symbol>/gaps.json` | Missing daily and minute open times |

## kdb/q

q is a separate install. kdb+ and the q language are products of KX Systems, Inc., and this package does not include the interpreter or a `k4.lic` / `kc.lic` key. Every kdb+ process needs your own KX license. Commercial use follows your agreement with KX, including the [On-Premise Licenced Software Terms, version 5.0](https://kx.com/legal/on-premise-licenced-software-terms/) (1 October 2026) and the [General Terms and Conditions, version 5.0](https://kx.com/legal/terms-and-conditions-v5-0/). [KDB-X Community Edition](https://code.kx.com/q/learn/licensing/) is free for personal and commercial use, subject to [KX's usage restrictions](https://code.kx.com/licensing/usage-restrictions.html). The commercial terms restrict combining the Licensed Software with copyleft materials. Read that term before loading these GPL scripts into a commercially licensed kdb+. Details and trademarks are in [NOTICE](../NOTICE).

The scripts live in `kdb/` and ship with the package. They are original krakentool source under GPL-3.0-or-later, not KX's tick.q. `krakentool q-path` prints that directory. Put the script name before `-p`, as in `q kdb/tick.q -p 5010`. An address without a port uses 5010.

`--q` and `--q-only` are on the live stream and on `history`. `dataset` does not publish live. It is loaded afterwards by `kdb/hdb.q`.

### Flow

![Live events into a tickerplant, a captured file into memory, and a dataset into a historical database](images/q-flow.svg)

Two live paths share one tickerplant. `--q` opens a kdb IPC session and calls `.kt.ingest` with one JSON object per event. The call is asynchronous, so the publisher does not wait for a reply. `KRAKENTOOL_PYKX=1` sends that same call through [PyKX](https://code.kx.com/pykx/) when PyKX is installed. Otherwise krakentool speaks IPC itself. PyKX is not installed by `uv sync`. Its source is Apache-2.0. The `q.so` library inside it is under KX's Software License for q.so. See [NOTICE](../NOTICE).

The pipe is the other live path. `kdb/feed.q` reads NDJSON from stdin and calls `.kt.ingest` on each line when stdin closes. Use `--q` when rows should arrive while the stream is still running.

`kdb/tick.q` routes on `channel`, or on `kind` for your own fills and orders. It replaces the default insert with a fan-out of `.kt.on` and does not store rows. `kdb/rdb.q` subscribes to all seven tables and inserts what it receives.

A captured file and a dataset stay in one q process. `kdb/stdin.q` loads NDJSON into the seven memory tables and leaves the prompt open. `kdb/hdb.q` reads `ohlcv-1d.jsonl`, `ohlcv-1m.jsonl`, and `trades.jsonl` from each symbol directory and writes a date-partitioned database with `.Q.dpft`, parted by `sym` and sorted by `sym` and `time`.

### Sequence

![Sequence from starting the tickerplant and realtime process through .kt.ingest and .kt.on](images/q-sequence.svg)

Start the tickerplant, then the realtime process, then krakentool. The realtime process has to be subscribed before events are published. The tickerplant does not replay earlier rows. Stdout still prints each event. `--q-only` publishes and skips stdout. `--q-only` without `--q` is an error.

### Live tables

`kdb/schema.q` builds these empty tables. Book and level 3 become one row per price level. The ticker column for the last trade price is `lastPx`, because `last` is a reserved name in q. The JSON field stays `last`.

| Table | One row is | Main columns |
| --- | --- | --- |
| `ticker` | One quote | `time`, `sym`, `asset`, `kind`, `bid`, `bidQty`, `ask`, `askQty`, `lastPx`, `volume`, `vwap` |
| `trade` | One print | `time`, `sym`, `asset`, `kind`, `side`, `price`, `qty`, `tradeId` |
| `book` | One level on one side | `time`, `sym`, `asset`, `kind`, `side`, `price`, `qty` |
| `level3` | One resting order | `time`, `sym`, `asset`, `kind`, `event`, `side`, `orderId`, `price`, `qty` |
| `ohlc` | One candle update | `time`, `sym`, `asset`, `kind`, `interval`, `open`, `high`, `low`, `close`, `vwap`, `volume`, `n` |
| `ownTrade` | One of your fills | `time`, `sym`, `asset`, `kind`, `side`, `price`, `qty`, `fee`, `maker`, `orderId`, `tradeId` |
| `ownOrder` | One of your order events | `time`, `sym`, `asset`, `kind`, `status`, `side`, `price`, `limitPrice`, `qty`, `filled`, `fee`, `orderId` |

`asset` is `crypto` or `forex`. `kind` is `snapshot` or `update`. Timestamps are q timestamps. A numeric JSON time is unix seconds, including a fractional part. An RFC3339 string such as `2026-11-01T01:56:00.000000Z` is accepted as well.

### Historical tables

| Table | Source file | Columns |
| --- | --- | --- |
| `ohlcv1d` | `ohlcv-1d.jsonl` | `time`, `sym`, `asset`, `interval`, `open`, `high`, `low`, `close`, `vwap`, `volume`, `n`, `gap` |
| `ohlcv1m` | `ohlcv-1m.jsonl` | same columns as `ohlcv1d` |
| `trades` | `trades.jsonl` | `time`, `sym`, `asset`, `side`, `typ`, `price`, `qty`, `tradeId` |

`gap` is true on a forward-filled candle. Symbol directories named like `BTC-USD` are read. `manifest.json` and other `*.json` files are skipped. Commands for each path are in [Sample commands](#sample-commands).

### Data browser

`kdb/browser.q` serves `web/` and answers four calls over the same port's websocket: `mode`, `catalog`, `columns`, and `rows`. The page is static. It draws the result with [AG Grid Community](https://www.ag-grid.com/) 32.3.3, which is MIT, Copyright (c) 2015-2024 AG GRID LTD. The permission notice shipped with the bundle is [web/vendor/ag-grid-community.MIT.txt](../web/vendor/ag-grid-community.MIT.txt). The enterprise edition is not included. The shape of the call, a JSON object with an id and a function name, follows the approach in KX's article [Single Page Applications and kdb+](https://kx.com/blog/single-page-applications-and-kdb-react/). [ticktrackerkdb](https://github.com/vvishwa/ticktrackerkdb) is a larger example of that approach. This browser is separate code, and the page cannot evaluate arbitrary q.

```bash
q kdb/browser.q -p 5012
q kdb/browser.q hdb -p 5012
q kdb/browser.q localhost:5010 -p 5012
```

No argument, and any argument containing `:`, subscribes to a tickerplant (`localhost:5010` when the address is omitted) and keeps the rows that arrive after the browser connects. The tickerplant does not replay earlier rows. A path loads that historical database and does not subscribe. Open `http://localhost:5012/`. The table list shows row counts. On a live feed the page opens `trade` when that table already has rows, and each new row is pushed into the grid while Live is on. The chart above the grid plots those same rows: candles when the table has open, high, low, and close, bid and ask together on a quote table, or any other numeric column from the series menu. Find and the symbol box apply to the chart as well as the grid. The symbol box limits which pushed rows are shown. Find filters the rows already on the page. The row limit keeps the newest rows.

A date-partitioned database often has a table in some dates and not others. The loader and the browser run `.Q.chk` so every date has every table, and a count does not stop on a missing partition. Rows are read a date at a time, newest date first, until the limit is filled.

## Sample commands

These assume [Get started](#get-started) has been run, so `uv run` uses the environment from `uv.lock`. Market events go to stdout. Connection status stays on stderr. `Ctrl-C` stops a live stream.

### Public market data

Crypto and forex share one socket. The default set is `BTC/USD`, `ETH/USD`, `SOL/USD`, `EUR/USD`, `GBP/USD`, and `USD/JPY`, on the `ticker` channel, with quotes published when the best bid or offer changes.

```bash
uv run krakentool
```

Ticker and trades for one crypto book and one forex book, printed as text for ten seconds:

```bash
uv run krakentool BTC/USD EUR/USD \
  --channels ticker,trade \
  --format text \
  --duration 10
```

Publish the ticker on prints instead of quote changes, and stop after 20 events:

```bash
uv run krakentool EUR/USD USD/JPY \
  --channels ticker \
  --event-trigger trades \
  --max-messages 20
```

Aggregated level 2 book, 25 levels per side, and one-minute candles. Heartbeats are not written to stdout. `--strict` exits if a symbol subscription is rejected. `--no-snapshot` waits for live updates.

```bash
uv run krakentool BTC/USD GBP/USD \
  --channels book,ohlc \
  --book-depth 25 \
  --ohlc-interval 1 \
  --strict \
  --duration 15
```

```bash
uv run krakentool SOL/USD --channels trade --no-snapshot --duration 10
```

### Level 3 order book

Level 3 is the per-order book. Depth is 10, 100, or 1000. It needs the same API key as `history`. The token is not printed.

```bash
uv run krakentool BTC/USD EUR/USD \
  --channels level3 \
  --l3-depth 10 \
  --format text \
  --duration 10
```

Public channels and level 3 cannot share a socket, so this opens both connections:

```bash
uv run krakentool BTC/USD EUR/USD \
  --channels ticker,level3 \
  --l3-depth 10 \
  --duration 10
```

### Your fills and orders

The snapshot is open orders plus the latest 50 fills. Older closed orders are not replayed. Credentials come from `KRAKEN_API_KEY` / `KRAKEN_API_SECRET` or from `kraken auth login`.

```bash
uv run krakentool history
uv run krakentool history --format text
```

Fills only, orders only, or the live feed after the snapshot. A symbol filter accepts v2 names (`BTC/USD`) and REST names (`XXBTZUSD`). `--no-open` skips the open-order snapshot.

```bash
uv run krakentool history BTC/USD --trades
uv run krakentool history --orders --no-open
uv run krakentool history --follow --duration 30
```

### Backtesting dataset

Daily candles for the long window. Minute candles and trade ticks share the drill window and have to sit inside the last 12 hours or so, because OHLC returns at most 720 bars. `dataset/` is gitignored.

Daily bars only, for crypto and forex:

```bash
uv run krakentool dataset BTC/USD EUR/USD \
  --start 2026-10-30 --end 2026-11-01 \
  --gaps exclude \
  --out dataset
```

Minute bars, trade ticks, and the VWAP check. Missing candles stay out of the series and are listed in `gaps.json`:

```bash
uv run krakentool dataset BTC/USD EUR/USD \
  --start 2026-10-30 --end 2026-11-01 \
  --drill-start 2026-11-01T01:56:00Z \
  --drill-end 2026-11-01T02:11:00Z \
  --minutes --ticks \
  --gaps exclude \
  --vwap-tolerance 0.0001 \
  --pause 0.25 \
  --max-trade-pages 30 \
  --out dataset
```

The same drill, with a hole filled by the previous close at zero volume:

```bash
uv run krakentool dataset BTC/USD \
  --start 2026-10-30 --end 2026-11-01 \
  --drill-start 2026-11-01T01:56:00Z \
  --drill-end 2026-11-01T02:11:00Z \
  --minutes --ticks \
  --gaps forward-fill \
  --out dataset
```

### kdb/q

q is already installed, `QHOME` points at it, and a KX license key (`k4.lic` or `kc.lic`) is in place. See [NOTICE](../NOTICE). The script name comes before `-p`. Start the tickerplant, then the realtime process, then publish. `--q-only` skips stdout. `history` accepts the same flags.

```bash
q kdb/tick.q -p 5010
q kdb/rdb.q localhost:5010
uv run krakentool BTC/USD EUR/USD \
  --channels ticker,trade,book,ohlc \
  --q localhost:5010 \
  --duration 10
uv run krakentool BTC/USD EUR/USD --channels level3 --l3-depth 10 --q localhost:5010 --q-only --duration 10
uv run krakentool history --q localhost:5010
```

Pipe NDJSON. Rows are forwarded when krakentool exits and the pipe closes:

```bash
uv run krakentool BTC/USD EUR/USD --channels ticker,trade --duration 10 \
  | q kdb/feed.q localhost:5010
```

Load a saved file into memory, or turn a dataset directory into a historical database. `krakentool q-path` prints the directory of these scripts. Set `KRAKENTOOL_PYKX=1` before `--q` when PyKX should carry the IPC call.

```bash
uv run krakentool q-path
q kdb/stdin.q events.jsonl
q kdb/hdb.q dataset hdb
q kdb/browser.q hdb -p 5012
```

## License

Copyright (C) 2026 aifintech-do. krakentool is free software under the GNU General Public License, version 3 or any later version, as published by the Free Software Foundation. The full text is [LICENSE](../LICENSE). There is no warranty. `krakentool --version` prints the short notice. Each source file carries the same copyright and license header.

The data browser uses AG Grid Community 32.3.3 under the MIT license, Copyright (c) 2015-2024 AG GRID LTD. The notice is [web/vendor/ag-grid-community.MIT.txt](../web/vendor/ag-grid-community.MIT.txt). [web/vendor/ag-grid-community.LICENSE.txt](../web/vendor/ag-grid-community.LICENSE.txt) is the upstream package list: community packages are MIT, and enterprise packages are commercial. Only the community bundle is in this repository. AG Grid is a product of AG Grid Ltd. krakentool is not affiliated with or endorsed by AG Grid Ltd. The `websockets` package stays under the BSD 3-Clause license that ships with it.

kdb+ and q are products of KX Systems, Inc. and are not covered by the GPL grant above. KX publishes the requirement that every kdb+ process have a license at [Licensing kdb+](https://code.kx.com/q/learn/licensing/). Commercial terms: [On-Premise Licenced Software Terms, version 5.0](https://kx.com/legal/on-premise-licenced-software-terms/) and [General Terms and Conditions, version 5.0](https://kx.com/legal/terms-and-conditions-v5-0/). Community Edition limits: [usage restrictions](https://code.kx.com/licensing/usage-restrictions.html). Optional PyKX is Apache-2.0 except `q.so`, which is under KX's [Software License for q.so](https://github.com/KxSystems/pykx/blob/main/LICENSE.txt). KX and kdb+ are registered trademarks of KX Systems, Inc. krakentool is not affiliated with or endorsed by KX. See [NOTICE](../NOTICE).
