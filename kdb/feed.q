/ Read krakentool NDJSON from stdin and forward each line to a tickerplant.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ krakentool BTC/USD EUR/USD --channels ticker,trade | q kdb/feed.q localhost:5010
/ Lines are forwarded when stdin closes.

addr:$[0=count .z.x; "localhost:5010"; .z.x 0];
h:hopen hsym `$addr;
lines:"\n" vs read0 0;
lines:{x where not x="\r"} each lines;
lines:lines where 0<count each lines;
{h(`.kt.ingest; x)} each lines;
exit 0;
