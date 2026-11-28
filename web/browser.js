/* krakentool data browser.
 * Copyright (C) 2026 aifintech-do
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Asks a kdb+ process for catalog, columns, and rows. The grid is AG Grid Community.
 */
(function () {
  const statusEl = document.getElementById("status");
  const tablesEl = document.getElementById("tables");
  const summaryEl = document.getElementById("summary");
  const limitEl = document.getElementById("limit");
  const symEl = document.getElementById("sym");
  const quickEl = document.getElementById("quick");
  const autoEl = document.getElementById("auto");
  const gridEl = document.getElementById("grid");
  const chartEl = document.getElementById("chart");
  const seriesEl = document.getElementById("chart-series");
  const chartSymEl = document.getElementById("chart-sym");
  const chartSymLabel = document.getElementById("chart-sym-label");
  const readoutEl = document.getElementById("chart-readout");

  const numeric = new Set(["f", "e", "i", "j", "h"]);
  let socket = null;
  let nextId = 1;
  const pending = new Map();
  let catalog = [];
  let selected = "";
  let timer = 0;
  let gridApi = null;
  let chartMeta = [];
  let chartPoints = [];
  let chartFrame = 0;
  let chartSymKey = "";

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = "status" + (kind ? " " + kind : "");
  }

  function rejectAll(reason) {
    pending.forEach(function (item) { item.reject(reason); });
    pending.clear();
  }

  function call(func, obj) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("not connected"));
    }
    const id = nextId++;
    return new Promise(function (resolve, reject) {
      pending.set(id, { resolve: resolve, reject: reject });
      socket.send(JSON.stringify({ id: id, func: func, obj: obj }));
    });
  }

  function connect() {
    const scheme = location.protocol === "https:" ? "wss://" : "ws://";
    const url = scheme + location.host + "/";
    setStatus("Connecting to " + url, "");
    socket = new WebSocket(url);
    socket.onopen = function () {
      setStatus("Connected", "ok");
      call("mode", null).then(function (mode) {
        if (mode && mode.live) {
          autoEl.checked = true;
          setStatus("Live " + (mode.source || ""), "ok");
          schedule();
        }
        loadCatalog();
      }).catch(function () {
        loadCatalog();
      });
    };
    socket.onclose = function () {
      setStatus("Disconnected", "bad");
      rejectAll(new Error("connection closed"));
    };
    socket.onerror = function () {
      setStatus("Connection failed", "bad");
    };
    socket.onmessage = function (event) {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (message.push && message.row) {
        onPush(message);
        return;
      }
      const item = pending.get(message.id);
      if (!item) return;
      pending.delete(message.id);
      if (message.ok) item.resolve(message.result);
      else item.reject(new Error(message.error || "request failed"));
    };
  }

  function renderTables() {
    tablesEl.replaceChildren();
    catalog.forEach(function (table) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.name = table.name;
      if (table.name === selected) button.setAttribute("aria-current", "true");
      const name = document.createElement("span");
      name.textContent = table.name;
      const count = document.createElement("span");
      count.className = "count";
      count.textContent = String(table.rows);
      button.append(name, count);
      button.addEventListener("click", function () {
        selected = table.name;
        renderTables();
        loadRows();
      });
      item.append(button);
      tablesEl.append(item);
    });
  }

  function loadCatalog() {
    call("catalog", null).then(function (rows) {
      catalog = Array.isArray(rows) ? rows : [];
      if (!selected && catalog.length) {
        const trade = catalog.find(function (table) { return table.name === "trade"; });
        selected = trade && trade.rows ? trade.name : catalog[0].name;
      }
      if (selected && !catalog.some(function (table) { return table.name === selected; })) {
        selected = catalog.length ? catalog[0].name : "";
      }
      renderTables();
      if (selected) loadRows();
      else summaryEl.textContent = "This process has no tables.";
    }).catch(function (err) {
      summaryEl.textContent = err.message;
    });
  }

  function numericNames(meta) {
    return (meta || []).filter(function (column) {
      return numeric.has(String(column.t || ""));
    }).map(function (column) { return column.c; });
  }

  function seriesChoices(meta) {
    const names = new Set(numericNames(meta));
    const choices = [];
    if (["open", "high", "low", "close"].every(function (name) { return names.has(name); })) {
      choices.push({ id: "ohlc", label: "OHLC" });
    }
    if (names.has("bid") && names.has("ask")) {
      choices.push({ id: "quote", label: "Bid / ask / last" });
    }
    names.forEach(function (name) { choices.push({ id: name, label: name }); });
    return choices;
  }

  function preferredSeries(choices) {
    const ids = choices.map(function (choice) { return choice.id; });
    const preferred = ["ohlc", "quote", "price", "lastPx", "close", "bid"];
    for (let i = 0; i < preferred.length; i += 1) {
      if (ids.indexOf(preferred[i]) !== -1) return preferred[i];
    }
    return ids.length ? ids[0] : "";
  }

  function syncSeries(meta) {
    const choices = seriesChoices(meta);
    const current = seriesEl.value;
    seriesEl.replaceChildren();
    choices.forEach(function (choice) {
      const option = document.createElement("option");
      option.value = choice.id;
      option.textContent = choice.label;
      seriesEl.append(option);
    });
    const keep = choices.some(function (choice) { return choice.id === current; });
    seriesEl.value = keep ? current : preferredSeries(choices);
    seriesEl.disabled = !choices.length;
  }

  function visibleRows() {
    if (!gridApi) return [];
    const rows = [];
    gridApi.forEachNodeAfterFilter(function (node) {
      if (node.data) rows.push(node.data);
    });
    return rows;
  }

  function syncChartSymbols(rows) {
    const counts = new Map();
    rows.forEach(function (row) {
      const sym = row.sym ? String(row.sym) : "";
      if (!sym) return;
      counts.set(sym, (counts.get(sym) || 0) + 1);
    });
    const symbols = Array.from(counts.keys()).sort(function (a, b) {
      return counts.get(b) - counts.get(a);
    });
    const key = symbols.join("|");
    if (key === chartSymKey) return;
    chartSymKey = key;
    const current = chartSymEl.value;
    chartSymEl.replaceChildren();
    symbols.forEach(function (sym) {
      const option = document.createElement("option");
      option.value = sym;
      option.textContent = sym;
      chartSymEl.append(option);
    });
    chartSymLabel.hidden = symbols.length < 2;
    if (symbols.indexOf(current) !== -1) chartSymEl.value = current;
    else if (symbols.length) chartSymEl.value = symbols[0];
  }

  function finite(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatNum(value, span) {
    const scale = span > 0 ? span : Math.abs(value);
    let digits = 2;
    if (scale < 10) digits = 4;
    if (scale < 0.1) digits = 5;
    if (scale < 0.01) digits = 6;
    return value.toFixed(digits);
  }

  function shortTime(value) {
    const text = String(value || "");
    return text.length >= 19 ? text.slice(11, 19) : text;
  }

  function scheduleDraw() {
    if (chartFrame) return;
    chartFrame = window.requestAnimationFrame(function () {
      chartFrame = 0;
      drawChart();
    });
  }

  function drawChart() {
    const width = chartEl.parentElement.clientWidth || 320;
    const height = 220;
    const dpr = window.devicePixelRatio || 1;
    chartEl.width = Math.floor(width * dpr);
    chartEl.height = Math.floor(height * dpr);
    chartEl.style.width = width + "px";
    chartEl.style.height = height + "px";
    const ctx = chartEl.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, width, height);
    chartPoints = [];

    const series = seriesEl.value;
    let source = visibleRows();
    syncChartSymbols(source);
    if (chartSymEl.value) {
      source = source.filter(function (row) { return String(row.sym || "") === chartSymEl.value; });
    }
    const rows = source.slice().reverse();
    const plot = rows.map(function (row) {
      if (series === "ohlc") {
        const open = finite(row.open);
        const high = finite(row.high);
        const low = finite(row.low);
        const close = finite(row.close);
        if (open === null || high === null || low === null || close === null) return null;
        return { row: row, values: [open, high, low, close], open: open, high: high, low: low, close: close };
      }
      const fields = series === "quote"
        ? ["bid", "ask", "lastPx"].filter(function (name) { return finite(row[name]) !== null || name !== "lastPx"; })
        : [series];
      const values = [];
      fields.forEach(function (name) {
        const number = finite(row[name]);
        if (number !== null) values.push(number);
      });
      if (!values.length) return null;
      return { row: row, fields: fields, values: values };
    }).filter(Boolean);

    if (!series || !plot.length) {
      ctx.fillStyle = "#52606d";
      ctx.font = "13px Segoe UI, Helvetica, Arial, sans-serif";
      ctx.fillText(series ? "No numeric values in the loaded rows." : "This table has no numeric column to chart.", 16, 28);
      readoutEl.textContent = "The loaded rows, oldest at the left.";
      return;
    }

    let min = Infinity;
    let max = -Infinity;
    plot.forEach(function (point) {
      point.values.forEach(function (value) {
        if (value < min) min = value;
        if (value > max) max = value;
      });
    });
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const span = max - min;
    const pad = span * 0.08;
    min -= pad;
    max += pad;
    const left = 84;
    const right = 12;
    const top = 12;
    const bottom = 28;
    const plotW = Math.max(1, width - left - right);
    const plotH = Math.max(1, height - top - bottom);
    function yOf(value) {
      return top + (max - value) / (max - min) * plotH;
    }
    function xOf(index) {
      return left + (plot.length === 1 ? plotW / 2 : index / (plot.length - 1) * plotW);
    }

    ctx.strokeStyle = "#e6ebf0";
    ctx.fillStyle = "#52606d";
    ctx.font = "11px Segoe UI, Helvetica, Arial, sans-serif";
    ctx.lineWidth = 1;
    for (let tick = 0; tick < 4; tick += 1) {
      const value = min + (max - min) * tick / 3;
      const y = yOf(value);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(width - right, y);
      ctx.stroke();
      ctx.fillText(formatNum(value, span), 8, y + 4);
    }
    ctx.fillText(shortTime(plot[0].row.time || plot[0].row.date), left, height - 8);
    const lastLabel = shortTime(plot[plot.length - 1].row.time || plot[plot.length - 1].row.date);
    ctx.fillText(lastLabel, Math.max(left, width - right - ctx.measureText(lastLabel).width), height - 8);

    if (series === "ohlc") {
      const slot = plotW / plot.length;
      const body = Math.max(1, Math.min(10, slot * 0.62));
      plot.forEach(function (point, index) {
        const x = left + (index + 0.5) * slot;
        const up = point.close >= point.open;
        ctx.strokeStyle = up ? "#0f6e56" : "#8a3b12";
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath();
        ctx.moveTo(x, yOf(point.high));
        ctx.lineTo(x, yOf(point.low));
        ctx.stroke();
        const y = Math.min(yOf(point.open), yOf(point.close));
        ctx.fillRect(x - body / 2, y, body, Math.max(1, Math.abs(yOf(point.close) - yOf(point.open))));
        chartPoints.push({
          x: x,
          text: shortTime(point.row.time || point.row.date) + "  O " + formatNum(point.open, span) + "  H " + formatNum(point.high, span) + "  L " + formatNum(point.low, span) + "  C " + formatNum(point.close, span)
        });
      });
      return;
    }

    const fields = series === "quote" ? ["bid", "ask", "lastPx"] : [series];
    const colors = { bid: "#0f6e56", ask: "#8a3b12", lastPx: "#1b2430" };
    fields.forEach(function (field, fieldIndex) {
      ctx.beginPath();
      ctx.strokeStyle = colors[field] || ["#0f6e56", "#1b2430", "#8a3b12"][fieldIndex % 3];
      ctx.lineWidth = 1.6;
      let started = false;
      plot.forEach(function (point, index) {
        const value = finite(point.row[field]);
        if (value === null) return;
        const x = xOf(index);
        const y = yOf(value);
        if (!started) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        started = true;
      });
      ctx.stroke();
    });
    plot.forEach(function (point, index) {
      const parts = [shortTime(point.row.time || point.row.date)];
      fields.forEach(function (field) {
        const value = finite(point.row[field]);
        if (value !== null) parts.push(field + " " + formatNum(value, span));
      });
      chartPoints.push({ x: xOf(index), text: parts.join("  ") });
    });
  }

  function columnDefs(meta) {
    return (meta || []).map(function (column) {
      const code = String(column.t || "");
      return {
        field: column.c,
        sortable: true,
        filter: numeric.has(code) ? "agNumberColumnFilter" : "agTextColumnFilter",
        resizable: true,
      };
    });
  }

  function loadRows() {
    if (!selected) return;
    const spec = { table: selected, limit: Number(limitEl.value) };
    const sym = symEl.value.trim();
    if (sym) spec.sym = sym;
    Promise.all([call("columns", selected), call("rows", spec)]).then(function (pair) {
      const meta = pair[0];
      const rows = pair[1];
      const loaded = Array.isArray(rows) ? rows.length : 0;
      const known = catalog.find(function (table) { return table.name === selected; });
      const total = known ? known.rows : loaded;
      summaryEl.textContent = sym
        ? selected + ": " + loaded + " latest rows for " + sym
        : selected + ": showing " + loaded + " of " + total;
      if (!gridApi) {
        gridApi = agGrid.createGrid(gridEl, {
          columnDefs: columnDefs(meta),
          rowData: rows,
          defaultColDef: { minWidth: 110 },
          animateRows: false,
          pagination: true,
          paginationPageSize: 100,
          paginationPageSizeSelector: [50, 100, 200],
        });
      } else {
        gridApi.setGridOption("columnDefs", columnDefs(meta));
        gridApi.setGridOption("rowData", rows);
      }
      chartMeta = meta || [];
      syncSeries(chartMeta);
      scheduleDraw();
    }).catch(function (err) {
      summaryEl.textContent = err.message;
    });
  }

  function bumpCount(name) {
    let known = catalog.find(function (table) { return table.name === name; });
    if (!known) {
      known = { name: name, rows: 0, columns: [] };
      catalog.push(known);
      renderTables();
    }
    known.rows += 1;
    const count = tablesEl.querySelector('button[data-name="' + name + '"] .count');
    if (count) count.textContent = String(known.rows);
    return known.rows;
  }

  function onPush(message) {
    const name = message.table;
    const row = message.row;
    if (!name || !row) return;
    const total = bumpCount(name);
    if (!autoEl.checked || name !== selected || !gridApi) return;
    const sym = symEl.value.trim();
    if (sym && row.sym !== sym) return;
    gridApi.applyTransaction({ add: [row], addIndex: 0 });
    const limit = Number(limitEl.value) || 200;
    const stale = [];
    const shown = gridApi.getDisplayedRowCount();
    for (let i = limit; i < shown; i += 1) {
      const node = gridApi.getDisplayedRowAtIndex(i);
      if (node) stale.push(node.data);
    }
    if (stale.length) gridApi.applyTransaction({ remove: stale });
    const loaded = Math.min(limit, gridApi.getDisplayedRowCount());
    summaryEl.textContent = sym
      ? selected + ": " + loaded + " latest rows for " + sym
      : selected + ": showing " + loaded + " of " + total;
    scheduleDraw();
  }

  function schedule() {
    window.clearInterval(timer);
    timer = 0;
    if (!autoEl.checked) return;
    timer = window.setInterval(function () {
      loadCatalog();
    }, 2000);
  }

  document.getElementById("toolbar").addEventListener("submit", function (event) {
    event.preventDefault();
    loadRows();
  });
  document.getElementById("refresh-catalog").addEventListener("click", loadCatalog);
  quickEl.addEventListener("input", function () {
    if (gridApi) gridApi.setGridOption("quickFilterText", quickEl.value);
    scheduleDraw();
  });
  seriesEl.addEventListener("change", scheduleDraw);
  chartSymEl.addEventListener("change", scheduleDraw);
  chartEl.addEventListener("mousemove", function (event) {
    if (!chartPoints.length) return;
    const x = event.offsetX;
    let nearest = chartPoints[0];
    let distance = Math.abs(nearest.x - x);
    chartPoints.forEach(function (point) {
      const gap = Math.abs(point.x - x);
      if (gap < distance) {
        nearest = point;
        distance = gap;
      }
    });
    readoutEl.textContent = nearest.text;
  });
  chartEl.addEventListener("mouseleave", function () {
    readoutEl.textContent = "The loaded rows, oldest at the left.";
  });
  window.addEventListener("resize", scheduleDraw);
  autoEl.addEventListener("change", schedule);
  limitEl.addEventListener("change", loadRows);
  connect();
})();
