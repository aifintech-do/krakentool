/ krakentool kdb schema and JSON ingest.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ Runs on kdb+, licensed separately by KX Systems, Inc. See NOTICE.
/ Tables are filled by .kt.fan. The tickerplant replaces .kt.fan so it only publishes.

.kt.at:{[d;k] $[k in key d; d k; `]}
.kt.sym:{[x] $[(abs type x)=11h; x; 10h=type x; `$x; `]}
.kt.f:{[x] $[(abs type x) in 5 6 7 8 9h; "f"$x; 10h=type x; "F"$x; 0n]}
.kt.flag:{[x] $[(abs type x)=1h; x; x in (1;1b); 0b]}
.kt.id:{[x]
  $[(abs type x)=11h; x;
    10h=type x; `$x;
    (abs type x) in 5 6 7 8 9h; `$string "j"$x;
    `]
  }
.kt.unix:{[x]
  s:"j"$x;
  nano:"j"$1000000000*(x-s);
  2000.01.01D00:00:00+(1000000000j*(s-946684800))+nano
  }
.kt.text:{[x]
  if["T" in x; y:ssr[ssr[ssr[x;"Z";""];"T";"D"];"-";"."]; :"P"$y];
  if[all x in .Q.n,".-+"; :.kt.unix "F"$x];
  0Np
  }
.kt.time:{[x]
  if[(abs type x)=12h; :x];
  if[(abs type x) in 5 6 7 8 9h; :.kt.unix x];
  if[10h=type x; :.kt.text x];
  0Np
  }
.kt.qty:{[d]
  q:.kt.f .kt.at[d;`qty];
  if[not null q; :q];
  q:.kt.f .kt.at[d;`volume];
  if[not null q; :q];
  .kt.f .kt.at[d;`order_qty]
  }
.kt.px:{[d]
  p:.kt.f .kt.at[d;`price];
  if[not null p; :p];
  p:.kt.f .kt.at[d;`limit_price];
  if[not null p; :p];
  .kt.f .kt.at[d;`bid]
  }

.kt.init:{
  ticker::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); bid:`float$(); bidQty:`float$(); ask:`float$(); askQty:`float$(); lastPx:`float$(); volume:`float$(); vwap:`float$());
  trade::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); side:`symbol$(); price:`float$(); qty:`float$(); tradeId:`symbol$());
  book::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); side:`symbol$(); price:`float$(); qty:`float$());
  level3::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); event:`symbol$(); side:`symbol$(); orderId:`symbol$(); price:`float$(); qty:`float$());
  ohlc::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); interval:`int$(); open:`float$(); high:`float$(); low:`float$(); close:`float$(); vwap:`float$(); volume:`float$(); n:`long$());
  ownTrade::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); side:`symbol$(); price:`float$(); qty:`float$(); fee:`float$(); maker:`boolean$(); orderId:`symbol$(); tradeId:`symbol$());
  ownOrder::([] time:`timestamp$(); sym:`symbol$(); asset:`symbol$(); kind:`symbol$(); status:`symbol$(); side:`symbol$(); price:`float$(); limitPrice:`float$(); qty:`float$(); filled:`float$(); fee:`float$(); orderId:`symbol$());
  }

/ Default fan writes into this process. tick.q replaces it with publish-only.
.kt.fan:{[name;row] name insert row}
.kt.rows:{[name;rows]
  if[99h=type rows; rows:enlist rows];
  if[0=count rows; :()];
  {[n;r] .kt.fan[n;r]}[name] each rows;
  }

.kt.ticker:{[e]
  .kt.rows[`ticker; enlist `time`sym`asset`kind`bid`bidQty`ask`askQty`lastPx`volume`vwap!(
    .kt.time .kt.at[e;`timestamp];
    .kt.sym .kt.at[e;`symbol];
    .kt.sym .kt.at[e;`asset_class];
    .kt.sym .kt.at[e;`type];
    .kt.f .kt.at[e;`bid];
    .kt.f .kt.at[e;`bid_qty];
    .kt.f .kt.at[e;`ask];
    .kt.f .kt.at[e;`ask_qty];
    .kt.f .kt.at[e;`last];
    .kt.f .kt.at[e;`volume];
    .kt.f .kt.at[e;`vwap])]
  }

.kt.trade:{[e]
  .kt.rows[`trade; enlist `time`sym`asset`kind`side`price`qty`tradeId!(
    .kt.time .kt.at[e;`timestamp];
    .kt.sym .kt.at[e;`symbol];
    .kt.sym .kt.at[e;`asset_class];
    .kt.sym .kt.at[e;`type];
    .kt.sym .kt.at[e;`side];
    .kt.px e;
    .kt.qty e;
    .kt.id .kt.at[e;`trade_id])]
  }

.kt.sideRows:{[e;side;col]
  raw:.kt.at[e;col];
  if[99h=type raw; raw:enlist raw];
  if[not (type raw) in 0 98h; :()];
  if[0=count raw; :()];
  ts:.kt.time .kt.at[e;`timestamp];
  sym:.kt.sym .kt.at[e;`symbol];
  asset:.kt.sym .kt.at[e;`asset_class];
  kind:.kt.sym .kt.at[e;`type];
  {[e;side;ts;sym;asset;kind;level]
    ev:.kt.sym .kt.at[level;`event];
    if[ev~`; ev:kind];
    `time`sym`asset`kind`event`side`orderId`price`qty!(
      $[null .kt.time .kt.at[level;`timestamp]; ts; .kt.time .kt.at[level;`timestamp]];
      sym; asset; kind; ev; side;
      .kt.id .kt.at[level;`order_id];
      .kt.px level;
      .kt.qty level)
    }[e;side;ts;sym;asset;kind] each raw
  }

.kt.book:{[e]
  rows:.kt.sideRows[e;`bid;`bids],.kt.sideRows[e;`ask;`asks];
  if[0=count rows; :()];
  .kt.rows[`book; {`time`sym`asset`kind`side`price`qty#x} each rows];
  }

.kt.level3:{[e]
  rows:.kt.sideRows[e;`bid;`bids],.kt.sideRows[e;`ask;`asks];
  if[0=count rows; :()];
  .kt.rows[`level3; rows];
  }

.kt.ohlc:{[e]
  t:.kt.at[e;`interval_begin];
  if[t~`; t:.kt.at[e;`timestamp]];
  .kt.rows[`ohlc; enlist `time`sym`asset`kind`interval`open`high`low`close`vwap`volume`n!(
    .kt.time t;
    .kt.sym .kt.at[e;`symbol];
    .kt.sym .kt.at[e;`asset_class];
    .kt.sym .kt.at[e;`type];
    "i"$.kt.f .kt.at[e;`interval];
    .kt.f .kt.at[e;`open];
    .kt.f .kt.at[e;`high];
    .kt.f .kt.at[e;`low];
    .kt.f .kt.at[e;`close];
    .kt.f .kt.at[e;`vwap];
    .kt.f .kt.at[e;`volume];
    "j"$.kt.f .kt.at[e;`trades])]
  }

.kt.ownTrade:{[e]
  .kt.rows[`ownTrade; enlist `time`sym`asset`kind`side`price`qty`fee`maker`orderId`tradeId!(
    .kt.time .kt.at[e;`time];
    .kt.sym .kt.at[e;`symbol];
    .kt.sym .kt.at[e;`asset_class];
    .kt.sym .kt.at[e;`type];
    .kt.sym .kt.at[e;`side];
    .kt.f .kt.at[e;`price];
    .kt.f .kt.at[e;`volume];
    .kt.f .kt.at[e;`fee];
    .kt.flag .kt.at[e;`maker];
    .kt.id .kt.at[e;`order_id];
    .kt.id .kt.at[e;`trade_id])]
  }

.kt.ownOrder:{[e]
  .kt.rows[`ownOrder; enlist `time`sym`asset`kind`status`side`price`limitPrice`qty`filled`fee`orderId!(
    .kt.time .kt.at[e;`time];
    .kt.sym .kt.at[e;`symbol];
    .kt.sym .kt.at[e;`asset_class];
    .kt.sym .kt.at[e;`type];
    .kt.sym .kt.at[e;`status];
    .kt.sym .kt.at[e;`side];
    .kt.f .kt.at[e;`price];
    .kt.f .kt.at[e;`limit_price];
    .kt.f .kt.at[e;`volume];
    .kt.f .kt.at[e;`volume_executed];
    .kt.f .kt.at[e;`fee];
    .kt.id .kt.at[e;`id])]
  }

.kt.ingest:{[text]
  event:.j.k text;
  ch:.kt.sym .kt.at[event;`channel];
  if[ch~`; ch:.kt.sym .kt.at[event;`kind]];
  $[
    ch=`ticker; .kt.ticker event;
    ch=`trade; .kt.trade event;
    ch=`book; .kt.book event;
    ch=`level3; .kt.level3 event;
    ch=`ohlc; .kt.ohlc event;
    ch in `own_trade`ownTrade; .kt.ownTrade event;
    ch in `own_order`ownOrder; .kt.ownOrder event;
    ()];
  }
