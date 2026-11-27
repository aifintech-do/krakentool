/ krakentool tickerplant. Listens for .kt.ingest and fans rows out to subscribers.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ Start with: q kdb/tick.q -p 5010
/ A subscriber calls .kt.sub[`ticker`trade`book`level3`ohlc`ownTrade`ownOrder]

.kdb.dir:{
  p:ssr[string .z.f;"\\";"/"];
  slash:last where "/"=p;
  $[null slash; ""; (slash+1)#p]
  }
system "l ",.kdb.dir[],"schema.q";
.kt.init[];
.kt.subs:([handle:`int$()] names:());
.kt.fan:{[name;row]
  hs:exec handle from .kt.subs where (0=count each names) or name in/:names;
  {[h;n;r] (neg h) (`.kt.on; n; r)}[;name;row] each hs;
  };
.kt.sub:{`.kt.subs upsert (.z.w; x)};
.z.pc:{delete from `.kt.subs where handle=x};
