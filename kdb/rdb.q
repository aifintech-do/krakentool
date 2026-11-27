/ krakentool realtime database. Subscribes to the tickerplant and keeps the tables in memory.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ Start with: q kdb/rdb.q localhost:5010

.kdb.dir:{
  p:ssr[string .z.f;"\\";"/"];
  slash:last where "/"=p;
  $[null slash; ""; (slash+1)#p]
  }
system "l ",.kdb.dir[],"schema.q";
.kt.init[];
.kt.on:{[name;row] name insert row};
addr:$[0=count .z.x; "localhost:5010"; .z.x 0];
h:hopen hsym `$addr;
h(`.kt.sub; `ticker`trade`book`level3`ohlc`ownTrade`ownOrder);
