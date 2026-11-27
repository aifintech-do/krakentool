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

  const numeric = new Set(["f", "e", "i", "j", "h"]);
  let socket = null;
  let nextId = 1;
  const pending = new Map();
  let catalog = [];
  let selected = "";
  let timer = 0;
  let gridApi = null;

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
      loadCatalog();
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
      if (!selected && catalog.length) selected = catalog[0].name;
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
    }).catch(function (err) {
      summaryEl.textContent = err.message;
    });
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
  });
  autoEl.addEventListener("change", schedule);
  limitEl.addEventListener("change", loadRows);
  connect();
})();
