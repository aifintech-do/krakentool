/ krakentool data browser. Serves web/ over HTTP and answers table reads over a websocket.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ Runs on kdb+, licensed separately by KX Systems, Inc. See NOTICE.
/ q kdb/browser.q -p 5012
/ q kdb/browser.q localhost:5010 -p 5012
/ q kdb/browser.q hdb -p 5012
/ No argument follows localhost:5010. An address follows that tickerplant.
/ A path loads a historical database and does not subscribe.
/ The page calls only mode, catalog, columns, and rows. It cannot evaluate arbitrary q.

.ktb.dir:{
  p:ssr[string .z.f;"\\";"/"];
  slash:last where "/"=p;
  $[null slash; ""; (slash+1)#p]
  };
.ktb.here:system "cd";
.ktb.web:(.ktb.here),"/",.ktb.dir[],"../web";
.ktb.arg:$[0<count .z.x; .z.x 0; ""];
.ktb.addr:$[0=count .ktb.arg; "localhost:5010"; .ktb.arg];
.ktb.wantlive:(0=count .ktb.arg) or ":" in .ktb.arg;
.ktb.live:0b;
.ktb.source:"";
.ktb.clients:`int$();
if[(0<count .ktb.arg) and not .ktb.wantlive;
  .ktb.db:hsym `$.ktb.arg;
  .ktb.filled:.Q.chk .ktb.db;
  system "l ",.ktb.arg;
 ];

.ktb.limit:{[x]
  n:$[(abs type x) in 5 6 7 8 9h; "j"$x; 10h=type x; "J"$x; 200];
  1|n&2000
  };
.ktb.asSym:{[x] $[(abs type x)=11h; x; 10h=type x; `$x; `]};
.ktb.table:{[name]
  t:.ktb.asSym name;
  if[not t in tables[]; '"unknown table"];
  t
  };
.ktb.catalog:{[ignored]
  names:asc tables[];
  {[n]
    t:value n;
    `name`rows`columns!(string n; count t; string cols t)
   } each names
  };
.ktb.columns:{[name]
  m:0!meta value .ktb.table name;
  flip `c`t`f`a!(string m`c; string each m`t; string m`f; string m`a)
  };
.ktb.plain:{[data]
  if[98h<>type data; :data];
  {[data;c]
    v:data c;
    $[11h=type first v; ![data; (); 0b; (enlist c)!enlist {raze string x} each v]; data]
   }/[data; cols data]
  };
.ktb.day:{[data;day;wanted;lim]
  slice:$[null wanted;
    select from data where date=day;
    select from data where date=day, sym=wanted];
  if[`time in cols slice; slice:`time xdesc slice];
  lim sublist slice
  };
.ktb.rows:{[spec]
  name:spec;
  lim:200;
  wanted:`;
  if[99h=type spec;
    name:$[`table in key spec; spec`table; `];
    lim:$[`limit in key spec; .ktb.limit spec`limit; 200];
    wanted:$[`sym in key spec; .ktb.asSym spec`sym; `];
   ];
  t:.ktb.table name;
  data:value t;
  if[`date in cols data;
    days:desc .Q.pv;
    acc:();
    i:0;
    while[(i<count days) and lim>count acc;
      slice:.ktb.day[data; days i; wanted; lim-count acc];
      acc:$[0=count acc; slice; acc,slice];
      i+:1
     ];
    :.ktb.plain acc
   ];
  data:0!data;
  if[not null wanted; if[`sym in cols data; data:select from data where sym=wanted]];
  if[`time in cols data; data:`time xdesc data];
  .ktb.plain lim sublist data
  };
.ktb.mode:{[ignored] `live`source!(.ktb.live; .ktb.source)};
.ktb.calls:`mode`catalog`columns`rows!(.ktb.mode;.ktb.catalog;.ktb.columns;.ktb.rows);
.ktb.push:{[name;row]
  if[0=count .ktb.clients; :()];
  rec:first .ktb.plain enlist row;
  msg:.j.j `push`table`row!(1b; string name; rec);
  {[h;m] @[neg[h]; m; {}]}[;msg] each .ktb.clients;
  };
.ktb.onfeed:{[name;row]
  .[insert; (name; row); {`}];
  .ktb.push[name; row];
  };
.ktb.attach:{[addr]
  .ktb.source:addr;
  system "l ",.ktb.dir[],"schema.q";
  .kt.init[];
  .kt.on:.ktb.onfeed;
  .ktb.link:@[{hopen hsym `$x}; addr; {0Ni}];
  if[null .ktb.link; -1 "tickerplant ",addr," is not open"; :()];
  .ktb.link(`.kt.sub; `ticker`trade`book`level3`ohlc`ownTrade`ownOrder);
  .ktb.live:1b;
  -1 "following ",addr;
  };
if[.ktb.wantlive; .ktb.attach .ktb.addr];
.z.wo:{.ktb.clients,:.z.w};
.z.wc:{.ktb.clients:.ktb.clients except x};
.ktb.errtext:{[body]
  $[10h=type body; body; -11h=type body; string body; raze string body]
  };
.ktb.send:{[id;ok;body]
  msg:$[ok; `id`ok`result!(id;1b;body); `id`ok`error!(id;0b;.ktb.errtext body)];
  neg[.z.w] .j.j msg
  };
.ktb.onmsg:{[raw]
  if[4h=abs type raw; raw:"c"$raw];
  parsed:@[.j.k; raw; {x}];
  if[not 99h=type parsed; :.ktb.send[0;0b;"expected a json object"]];
  id:0;
  if[`id in key parsed; id:"j"$parsed`id];
  fn:`;
  if[`func in key parsed; fn:`$parsed`func];
  if[not fn in key .ktb.calls; :.ktb.send[id;0b;"unknown call"]];
  arg:();
  if[`obj in key parsed; arg:parsed`obj];
  res:@[(.ktb.calls fn); arg; {x}];
  if[10h=type res; :.ktb.send[id;0b;res]];
  .ktb.send[id;1b;res]
  };
.z.ws:{[raw] .[.ktb.onmsg; enlist raw; {[e] .ktb.send[0;0b;e]}] };

.ktb.mime:("html";"css";"js";"txt")!("text/html; charset=utf-8";"text/css; charset=utf-8";"text/javascript; charset=utf-8";"text/plain; charset=utf-8");
.ktb.reply:{[status;mime;body]
  "HTTP/1.1 ",status,"\r\nContent-Type: ",mime,"\r\nContent-Length: ",(string count body),"\r\nConnection: close\r\n\r\n",body
  };
.ktb.missing:{.ktb.reply["404 Not Found";"text/plain"; "not found"]};
.z.ph:{[x]
  raw:x 0;
  path:$[raw like "GET *"; (" " vs raw) 1; raw];
  path:first "?" vs path;
  if[path like "/*"; path:1_path];
  if[path in (""; "/"); path:"index.html"];
  if[0<count ss[path; ".."]; :.ktb.missing[]];
  ext:last "." vs path;
  if[not ext in key .ktb.mime; :.ktb.missing[]];
  file:hsym `$ .ktb.web,"/",path;
  if[()~key file; :.ktb.missing[]];
  lines:read0 file;
  body:$[0=count lines; ""; ("\n" sv lines),"\n"];
  .ktb.reply["200 OK"; .ktb.mime ext; body]
  };
-1 "krakentool browser http://localhost:",string[system "p"],"/";
