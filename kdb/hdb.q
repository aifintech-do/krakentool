/ Load a krakentool dataset directory into a date-partitioned kdb database.
/ Copyright (C) 2026 aifintech-do
/ SPDX-License-Identifier: GPL-3.0-or-later
/ q kdb/hdb.q dataset hdb

if[2>count .z.x; -1 "usage: q kdb/hdb.q dataset hdb"; exit 1];
.kthdb.root:hsym `$ .z.x 0;
.kthdb.out:hsym `$ .z.x 1;

.kthdb.unix:{[x]
  s:"j"$x;
  nano:"j"$1000000000*(x-s);
  2000.01.01D00:00:00+(1000000000j*(s-946684800))+nano
  }
.kthdb.time:{[x]
  $[(abs type x) in 5 6 7 8 9h; .kthdb.unix x;
    10h=type x; $[all x in .Q.n,".-+"; .kthdb.unix "F"$x; "P"$ssr[ssr[ssr[x;"Z";""];"T";"D"];"-";"."]];
    0Np]
  }
.kthdb.exists:{not ()~key x}
.kthdb.read:{[path]
  if[not .kthdb.exists path; :()];
  lines:read0 path;
  lines:lines where 0<count each lines;
  .j.k each lines
  }
.kthdb.candle:{[rows]
  if[0=count rows; :()];
  flip `time`sym`asset`interval`open`high`low`close`vwap`volume`n`gap!flip {
    (
      .kthdb.time x`time;
      `$x`symbol;
      `$x`asset_class;
      "i"$x`interval;
      "f"$x`open;
      "f"$x`high;
      "f"$x`low;
      "f"$x`close;
      "f"$x`vwap;
      "f"$x`volume;
      "j"$x`count;
      $[(abs type x`gap)=1h; x`gap; 0b]
    )
   } each rows
  }
.kthdb.trades:{[rows]
  if[0=count rows; :()];
  flip `time`sym`asset`side`typ`price`qty`tradeId!flip {
    (
      .kthdb.time x`time;
      `$x`symbol;
      `$x`asset_class;
      `$string x`side;
      `$string x`order_type;
      "f"$x`price;
      "f"$x`volume;
      `$string "j"$x`trade_id
    )
   } each rows
  }
.kthdb.join:{[acc;add] $[0=count acc; add; 0=count add; acc; acc,add]}
.kthdb.save:{[name;data]
  if[0=count data; :()];
  dates:exec distinct `date$time from data;
  {[name;data;d]
    slice:`sym`time xasc select from data where d=`date$time;
    name set slice;
    .Q.dpft[.kthdb.out;d;`sym;name];
   }[name;data] each dates;
  }

.kthdb.daily:();
.kthdb.minute:();
.kthdb.ticks:();
names:key .kthdb.root;
names:names where not names like "*.json";
{
  dir:`$ string[.kthdb.root],"/",string x;
  .kthdb.daily:.kthdb.join[.kthdb.daily; .kthdb.candle .kthdb.read `$string[dir],"/ohlcv-1d.jsonl"];
  .kthdb.minute:.kthdb.join[.kthdb.minute; .kthdb.candle .kthdb.read `$string[dir],"/ohlcv-1m.jsonl"];
  .kthdb.ticks:.kthdb.join[.kthdb.ticks; .kthdb.trades .kthdb.read `$string[dir],"/trades.jsonl"];
 } each names;
.kthdb.save[`ohlcv1d; .kthdb.daily];
.kthdb.save[`ohlcv1m; .kthdb.minute];
.kthdb.save[`trades; .kthdb.ticks];
-1 "wrote ",(string count .kthdb.daily)," daily, ",(string count .kthdb.minute)," minute, ",(string count .kthdb.ticks)," trades";
