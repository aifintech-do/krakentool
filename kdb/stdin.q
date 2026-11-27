/ Load a captured krakentool NDJSON file into the in-memory tables.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ Runs on kdb+, licensed separately by KX Systems, Inc. See NOTICE.
/ q kdb/stdin.q events.jsonl

.kdb.dir:{
  p:ssr[string .z.f;"\\";"/"];
  slash:last where "/"=p;
  $[null slash; ""; (slash+1)#p]
  }
system "l ",.kdb.dir[],"schema.q";
.kt.init[];
if[0=count .z.x; -1 "usage: q kdb/stdin.q events.jsonl"; exit 1];
lines:read0 hsym `$ .z.x 0;
lines:lines where 0<count each lines;
.kt.ingest each lines;
