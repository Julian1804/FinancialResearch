import { setResultPanel } from "./ai-bridge.js";
import { workspaceApi } from "./api.js";
import { escapeHtml, head } from "./components.js";
import { lang } from "./i18n.js";

const EMPTY_STATE = {
  databases: [],
  catalogs: [],
  tables: [],
  selectedDatabase: "",
  selectedCatalog: "",
  selectedTable: "",
  detail: null,
  sample: null,
  raw: null,
  trace: null,
  qa: null,
  activeTab: "columns",
  filter: "",
  loading: false,
  error: "",
};

let browserState = { ...EMPTY_STATE };
let advancedRenderer = null;
let advancedLoaded = false;
let pageMode = "database";
let requestedTarget = null;

const COPY = {
  zh: {
    kicker: "\u6570\u636e\u5e93",
    title: "\u6570\u636e\u5e93",
    subtitle: "\u67e5\u770b\u672c\u5730\u6570\u636e\u5e93\u3001\u76ee\u5f55\u3001\u8868\u3001\u5b57\u6bb5\u3001\u6837\u4f8b\u6570\u636e\u3001\u539f\u59cb\u8f7d\u8377\u3001\u6765\u6e90\u8ffd\u8e2a\u548c\u8d28\u91cf\u8bb0\u5f55\u3002",
    database: "\u6570\u636e\u5e93",
    catalog: "\u76ee\u5f55",
    table: "\u8868",
    columns: "\u5b57\u6bb5",
    sample: "\u6837\u4f8b\u6570\u636e",
    raw: "\u539f\u59cb\u8f7d\u8377",
    source: "\u6765\u6e90\u8ffd\u8e2a",
    qa: "\u8d28\u91cf / \u963b\u585e",
    rows: "\u884c\u6570",
    actualUpdate: "\u6700\u8fd1\u5b9e\u9645\u66f4\u65b0\u65f6\u95f4",
    latestDate: "\u6700\u65b0\u6570\u636e\u65e5\u671f",
    sourceInterface: "\u6765\u6e90\u63a5\u53e3",
    sourceTier: "\u6765\u6e90\u7b49\u7ea7",
    readOnly: "\u53ea\u8bfb",
    notDeclared: "\u672a\u58f0\u660e",
    notFullCoverage: "\u8986\u76d6\u8303\u56f4\u6807\u8bb0",
    blockers: "\u963b\u585e\u9879",
    selectTable: "\u9009\u62e9\u4e00\u4e2a\u8868\u67e5\u770b\u5b57\u6bb5\u3001\u6837\u4f8b\u6570\u636e\u548c\u6765\u6e90\u8ffd\u8e2a\u3002",
    search: "\u641c\u7d22\u8868\u540d",
    noTables: "\u5f53\u524d\u76ee\u5f55\u6ca1\u6709\u53ef\u67e5\u770b\u7684\u8868\u3002",
    noRows: "\u6ca1\u6709\u6837\u4f8b\u884c\u3002",
    noBlockers: "\u672a\u8bb0\u5f55\u963b\u585e\u9879\u3002",
    loading: "\u6b63\u5728\u52a0\u8f7d\u6570\u636e\u5e93\u6d4f\u89c8\u5668\u2026",
    loadError: "\u6570\u636e\u5e93\u6d4f\u89c8\u5668\u52a0\u8f7d\u5931\u8d25",
    tableSummary: "\u8868\u6458\u8981",
    advanced: "\u9ad8\u7ea7\u8bca\u65ad",
    advancedLoading: "\u6b63\u5728\u52a0\u8f7d\u6280\u672f\u8bca\u65ad\u2026",
    column: "\u5b57\u6bb5",
    type: "\u7c7b\u578b",
    nullable: "\u53ef\u7a7a",
    role: "\u8bed\u4e49\u89d2\u8272",
    unit: "\u5355\u4f4d",
    frequency: "\u9891\u7387",
    yes: "\u662f",
    no: "\u5426",
    databaseNames: {
      machine_authorized_production_observations: "\u751f\u4ea7\u76ee\u6807",
      machine_authorized_production_references: "\u53c2\u8003 / \u4e3b\u6570\u636e",
      production_catalog_index: "\u751f\u4ea7\u76ee\u5f55\u7d22\u5f15",
      raw_data_artifacts: "\u539f\u59cb\u6570\u636e",
      production_ready_artifacts: "\u751f\u4ea7\u5c31\u7eea\u6570\u636e",
      quarantine_and_blockers: "\u9694\u79bb / \u963b\u585e",
      update_logs: "\u66f4\u65b0\u65e5\u5fd7",
    },
  },
  en: {
    kicker: "Database",
    title: "Database",
    subtitle: "View local databases, catalogs, tables, columns, sample rows, raw payloads, source trace, and quality records.",
    database: "Database",
    catalog: "Catalog",
    table: "Table",
    columns: "Columns",
    sample: "Sample Rows",
    raw: "Raw Payload",
    source: "Source Trace",
    qa: "QA / Blockers",
    rows: "Rows",
    actualUpdate: "Latest Actual Update Time",
    latestDate: "Latest Data Date",
    sourceInterface: "Source Interface",
    sourceTier: "Source Tier",
    readOnly: "Read-only",
    notDeclared: "Not declared",
    notFullCoverage: "Coverage Scope Flag",
    blockers: "Blockers",
    selectTable: "Select a table to view columns, sample rows, and source trace.",
    search: "Filter table names",
    noTables: "No viewable tables in this catalog.",
    noRows: "No sample rows.",
    noBlockers: "No blockers recorded.",
    loading: "Loading database browser\u2026",
    loadError: "Database browser failed to load",
    tableSummary: "Table Summary",
    advanced: "Advanced diagnostics",
    advancedLoading: "Loading technical diagnostics\u2026",
    column: "Column",
    type: "Type",
    nullable: "Nullable",
    role: "Semantic Role",
    unit: "Unit",
    frequency: "Frequency",
    yes: "Yes",
    no: "No",
    databaseNames: {
      machine_authorized_production_observations: "Production Target",
      machine_authorized_production_references: "Reference / Master Data",
      production_catalog_index: "Production Catalog Index",
      raw_data_artifacts: "Raw Data",
      production_ready_artifacts: "Production-ready Data",
      quarantine_and_blockers: "Quarantine / Blockers",
      update_logs: "Update Logs",
    },
  },
};

const SQL_PAGE_COPY = {
  zh: {
    kicker: "\u6570\u636e\u6d4f\u89c8\u5668",
    title: "SQL \u6570\u636e\u6d4f\u89c8\u5668",
    subtitle: "\u6309\u6570\u636e\u5e93\u3001\u76ee\u5f55\u548c\u8868\u67e5\u770b FR \u7684\u7269\u7406\u4e0e\u903b\u8f91\u6570\u636e\u7ed3\u6784\u3001\u5b57\u6bb5\u548c\u6837\u4f8b\u3002",
  },
  en: {
    kicker: "Data Explorer",
    title: "SQL Data Explorer",
    subtitle: "Inspect FR physical and logical databases, catalogs, tables, columns, and samples.",
  },
};

function copy() {
  const language = lang();
  const base = COPY[language] || COPY.zh;
  return pageMode === "sql" ? { ...base, ...(SQL_PAGE_COPY[language] || SQL_PAGE_COPY.zh) } : base;
}

function value(input, fallback = "") {
  return escapeHtml(input === undefined || input === null || input === "" ? fallback : String(input));
}

function databaseLabel(databaseId) {
  const database = browserState.databases.find((item) => item.database_id === databaseId) || {};
  return copy().databaseNames[databaseId] || database.label || databaseId;
}

function friendlyTier(tier) {
  const c = copy();
  const normalized = String(tier || "").toLowerCase();
  const labels = lang() === "en"
    ? { l0: "Official source", l1: "Validated source", l2: "Secondary source", l3: "Diagnostic source", t0_official: "Official source", t1_validated: "Validated source", t2_reputable_structured_provider: "Validated structured source", t3_diagnostic: "Diagnostic source", mixed: "Mixed sources" }
    : { l0: "\u5b98\u65b9\u6765\u6e90", l1: "\u5df2\u6821\u9a8c\u6765\u6e90", l2: "\u6b21\u7ea7\u6765\u6e90", l3: "\u8bca\u65ad\u6765\u6e90", t0_official: "\u5b98\u65b9\u6765\u6e90", t1_validated: "\u5df2\u6821\u9a8c\u6765\u6e90", t2_reputable_structured_provider: "\u5df2\u6821\u9a8c\u7ed3\u6784\u5316\u6765\u6e90", t3_diagnostic: "\u8bca\u65ad\u6765\u6e90", mixed: "\u591a\u7c7b\u6765\u6e90" };
  return labels[normalized] || (normalized === "not_declared" ? c.notDeclared : (tier || c.notDeclared));
}

function declaredValue(input) {
  return String(input || "").toLowerCase() === "not_declared" ? copy().notDeclared : (input || copy().notDeclared);
}

function tableById(tableId) {
  return browserState.tables.find((item) => item.table_id === tableId) || null;
}

function jsonBlock(payload) {
  return `<pre class="database-browser-json">${escapeHtml(JSON.stringify(payload ?? {}, null, 2))}</pre>`;
}

function dataTable(headers, rows, emptyText) {
  if (!rows.length) return `<div class="empty">${escapeHtml(emptyText)}</div>`;
  return `<div class="table-scroll"><table class="table database-browser-table"><thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${value(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function columnsPanel() {
  const c = copy();
  const columns = browserState.detail?.columns || [];
  return dataTable(
    [c.column, c.type, c.nullable, c.role, c.unit, c.frequency],
    columns.map((column) => [
      column.column_name,
      column.type,
      column.nullable ? c.yes : c.no,
      column.semantic_role || c.notDeclared,
      declaredValue(column.unit),
      declaredValue(column.frequency),
    ]),
    c.noRows,
  );
}

function samplePanel() {
  const c = copy();
  const rows = browserState.sample?.rows || [];
  const headers = Object.keys(rows[0] || {}).slice(0, 10);
  return dataTable(headers, rows.slice(0, 20).map((row) => headers.map((header) => {
    const cell = row[header];
    return typeof cell === "object" && cell !== null ? JSON.stringify(cell) : cell;
  })), c.noRows);
}

function sourcePanel() {
  const c = copy();
  const trace = browserState.trace?.source_trace || {};
  const fields = [
    [c.sourceInterface, trace.source_function_or_interface],
    [c.sourceTier, friendlyTier(trace.source_tier)],
    [c.actualUpdate, trace.latest_actual_update_time],
    [c.latestDate, trace.latest_observation_date],
  ];
  return `<dl class="database-browser-facts">${fields.map(([label, item]) => `<div><dt>${escapeHtml(label)}</dt><dd>${value(item, c.notDeclared)}</dd></div>`).join("")}</dl>`;
}

function qaPanel() {
  const c = copy();
  const blockers = browserState.qa?.blockers || [];
  if (!blockers.length) return `<div class="empty">${escapeHtml(c.noBlockers)}</div>`;
  return `<ul class="database-browser-blockers">${blockers.map((blocker) => `<li>${value(typeof blocker === "object" ? blocker.blocker || blocker.reason || JSON.stringify(blocker) : blocker)}</li>`).join("")}</ul>`;
}

function detailPanel() {
  const c = copy();
  if (!browserState.selectedTable) {
    return `<div class="database-browser-placeholder"><h2>${escapeHtml(c.table)}</h2><p>${escapeHtml(c.selectTable)}</p></div>`;
  }
  if (browserState.loading) return `<div class="empty">${escapeHtml(c.loading)}</div>`;
  const tabs = [
    ["columns", c.columns],
    ["sample", c.sample],
    ["raw", c.raw],
    ["source", c.source],
    ["qa", c.qa],
  ];
  const panels = {
    columns: columnsPanel,
    sample: samplePanel,
    raw: () => jsonBlock(browserState.raw?.raw_payload || {}),
    source: sourcePanel,
    qa: qaPanel,
  };
  const table = browserState.detail?.table || tableById(browserState.selectedTable) || {};
  return `<div class="database-browser-detail-head"><div><div class="eyebrow">${escapeHtml(c.table)}</div><h2>${value(table.table_name, c.table)}</h2></div><span class="tag">${escapeHtml(c.readOnly)}</span></div>
    <div class="database-browser-tabs" role="tablist" aria-label="${escapeHtml(c.table)}">
      ${tabs.map(([id, label]) => `<button class="btn ${browserState.activeTab === id ? "active" : ""}" role="tab" aria-selected="${browserState.activeTab === id}" data-browser-tab="${id}">${escapeHtml(label)}</button>`).join("")}
    </div>
    <section class="database-browser-tab-panel" data-browser-tab-panel="${browserState.activeTab}">${panels[browserState.activeTab]()}</section>`;
}

function databasePane() {
  const c = copy();
  return `<nav class="database-browser-pane database-browser-databases" aria-label="${escapeHtml(c.database)}">
    <div class="database-browser-pane-head"><h2>${escapeHtml(c.database)}</h2><span class="tag ok">${escapeHtml(c.readOnly)}</span></div>
    <div class="database-browser-choice-list">
      ${browserState.databases.map((database) => `<button class="database-browser-choice ${database.database_id === browserState.selectedDatabase ? "active" : ""}" data-browser-database="${value(database.database_id)}"><strong>${value(databaseLabel(database.database_id))}</strong><span>${value(database.storage, c.readOnly)}</span></button>`).join("")}
    </div>
  </nav>`;
}

function navigationPane() {
  const c = copy();
  const filter = browserState.filter.trim().toLowerCase();
  const tables = browserState.tables.filter((table) => !filter || String(table.table_name || "").toLowerCase().includes(filter));
  return `<aside class="database-browser-pane database-browser-navigation">
    <section>
      <h2>${escapeHtml(c.catalog)}</h2>
      <div class="database-browser-choice-list">
        ${browserState.catalogs.map((catalog) => `<button class="database-browser-choice ${catalog.catalog_id === browserState.selectedCatalog ? "active" : ""}" data-browser-catalog="${value(catalog.catalog_id)}"><strong>${value(catalog.label || catalog.catalog_id)}</strong></button>`).join("")}
      </div>
    </section>
    <section class="database-browser-table-list">
      <label class="database-browser-filter"><span>${escapeHtml(c.table)}</span><input class="input" type="search" value="${value(browserState.filter)}" placeholder="${escapeHtml(c.search)}" data-browser-filter></label>
      <div class="database-browser-choice-list" data-browser-table-list>
        ${tables.map((table) => `<button class="database-browser-choice ${table.table_id === browserState.selectedTable ? "active" : ""}" data-browser-table="${value(table.table_id)}"><strong>${value(table.table_name)}</strong><span>${value(table.row_count, "0")} ${escapeHtml(c.rows)}</span></button>`).join("") || `<div class="empty">${escapeHtml(c.noTables)}</div>`}
      </div>
    </section>
  </aside>`;
}

function advancedDiagnostics() {
  if (!advancedRenderer) return "";
  const c = copy();
  return `<details class="database-browser-advanced" data-advanced-diagnostics>
    <summary>${escapeHtml(c.advanced)}</summary>
    <div data-advanced-diagnostics-body><div class="empty">${escapeHtml(c.advancedLoading)}</div></div>
  </details>`;
}

function render() {
  const c = copy();
  const root = document.getElementById("workspace-main");
  if (!root) return;
  const primaryAttribute = pageMode === "sql" ? "data-sql-browser-primary" : "data-database-browser-primary";
  root.innerHTML = `<div class="page database-status database-browser-page" ${primaryAttribute}>
    ${head(c.kicker, c.title, c.subtitle)}
    ${browserState.error ? `<div class="risk">${escapeHtml(c.loadError)}: ${escapeHtml(browserState.error)}</div>` : ""}
    <section class="database-browser-workspace" aria-label="${escapeHtml(c.title)}">
      ${databasePane()}
      ${navigationPane()}
      <main class="database-browser-detail">${detailPanel()}</main>
    </section>
    ${advancedDiagnostics()}
  </div>`;
  bind();
}

function bridgeEmpty() {
  const c = copy();
  setResultPanel("database", {
    title: c.tableSummary,
    eyebrow: c.database,
    summary: c.selectTable,
    statusText: c.readOnly,
    html: `<div class="result-empty" data-browser-bridge-empty>${escapeHtml(c.selectTable)}</div>`,
  });
}

function bridgeSelected() {
  const c = copy();
  const table = browserState.detail?.table || tableById(browserState.selectedTable) || {};
  const facts = [
    [c.database, databaseLabel(browserState.selectedDatabase)],
    [c.catalog, browserState.selectedCatalog],
    [c.table, table.table_name],
    [c.rows, table.row_count],
    [c.actualUpdate, table.latest_actual_update_time],
    [c.latestDate, table.latest_observation_date],
    [c.sourceInterface, table.source_function_or_interface],
    [c.sourceTier, friendlyTier(table.source_tier)],
    [c.notFullCoverage, table.not_full_coverage_flag ? c.yes : c.no],
    [c.blockers, table.blocker_count ?? 0],
  ];
  setResultPanel("database", {
    title: table.table_name || c.tableSummary,
    eyebrow: c.tableSummary,
    summary: `${databaseLabel(browserState.selectedDatabase)} / ${browserState.selectedCatalog || c.notDeclared}`,
    statusText: c.readOnly,
    html: `<section class="database-table-summary" data-browser-table-summary><h3>${escapeHtml(c.tableSummary)}</h3><dl>${facts.map(([label, item]) => `<div><dt>${escapeHtml(label)}</dt><dd>${value(item, c.notDeclared)}</dd></div>`).join("")}</dl></section>`,
  });
}

async function loadNavigation(databaseId, catalogId = "") {
  const api = workspaceApi.researchWorkspace.databaseBrowser;
  browserState.loading = true;
  browserState.selectedDatabase = databaseId;
  browserState.selectedTable = "";
  browserState.detail = null;
  render();
  const catalogPayload = await api.catalogs(databaseId);
  const catalogs = catalogPayload.catalogs || [];
  const selectedCatalog = catalogId || catalogs[0]?.catalog_id || "";
  const tablePayload = selectedCatalog ? await api.tables(databaseId, selectedCatalog) : { tables: [] };
  browserState = {
    ...browserState,
    catalogs,
    tables: tablePayload.tables || [],
    selectedCatalog,
    selectedTable: "",
    loading: false,
    error: "",
  };
  bridgeEmpty();
  render();
}

async function selectTable(tableId) {
  const api = workspaceApi.researchWorkspace.databaseBrowser;
  browserState.selectedTable = tableId;
  browserState.activeTab = "columns";
  browserState.loading = true;
  render();
  const databaseId = browserState.selectedDatabase;
  const [detail, sample, raw, trace, qa] = await Promise.all([
    api.tableDetail(databaseId, tableId),
    api.sample(databaseId, tableId, 50, 0),
    api.rawPayload(databaseId, tableId),
    api.sourceTrace(databaseId, tableId),
    api.qaBlockers(databaseId, tableId),
  ]);
  browserState = { ...browserState, detail, sample, raw, trace, qa, loading: false, error: "" };
  render();
  bridgeSelected();
}

async function openAdvanced(details) {
  if (advancedLoaded || !advancedRenderer) return;
  advancedLoaded = true;
  const target = details.querySelector("[data-advanced-diagnostics-body]");
  try {
    await advancedRenderer(target);
  } catch (error) {
    target.innerHTML = `<div class="risk">${escapeHtml(error.message || String(error))}</div>`;
  }
}

function bind() {
  document.querySelectorAll("[data-browser-database]").forEach((button) => {
    button.onclick = () => loadNavigation(button.dataset.browserDatabase).catch(showError);
  });
  document.querySelectorAll("[data-browser-catalog]").forEach((button) => {
    button.onclick = () => loadNavigation(browserState.selectedDatabase, button.dataset.browserCatalog).catch(showError);
  });
  document.querySelectorAll("[data-browser-table]").forEach((button) => {
    button.onclick = () => selectTable(button.dataset.browserTable).catch(showError);
  });
  document.querySelectorAll("[data-browser-tab]").forEach((button) => {
    button.onclick = () => {
      browserState.activeTab = button.dataset.browserTab;
      render();
      bridgeSelected();
    };
  });
  document.querySelector("[data-browser-filter]")?.addEventListener("input", (event) => {
    browserState.filter = event.target.value;
    render();
    const input = document.querySelector("[data-browser-filter]");
    input?.focus();
    input?.setSelectionRange(input.value.length, input.value.length);
  });
  const details = document.querySelector("[data-advanced-diagnostics]");
  details?.addEventListener("toggle", () => {
    if (details.open) openAdvanced(details);
  });
}

function showError(error) {
  browserState.loading = false;
  browserState.error = error.message || String(error);
  render();
}

export async function renderDatabaseBrowserPage(options = {}) {
  pageMode = options.mode || "database";
  requestedTarget = options.initialTarget || null;
  advancedRenderer = options.renderAdvancedDiagnostics || null;
  advancedLoaded = false;
  browserState = { ...EMPTY_STATE, loading: true };
  bridgeEmpty();
  render();
  try {
    const payload = await workspaceApi.researchWorkspace.databaseBrowser.databases();
    browserState.databases = payload.databases || [];
    const firstDatabase = requestedTarget?.database_id || browserState.databases[0]?.database_id || "";
    if (firstDatabase) {
      await loadNavigation(firstDatabase, requestedTarget?.catalog_id || "");
      if (requestedTarget?.table_id && browserState.tables.some((row) => row.table_id === requestedTarget.table_id)) {
        await selectTable(requestedTarget.table_id);
      }
    } else {
      browserState.loading = false;
      render();
    }
  } catch (error) {
    showError(error);
  }
}

export async function renderSqlExplorerPage(options = {}) {
  await renderDatabaseBrowserPage({ ...options, mode: "sql", renderAdvancedDiagnostics: null });
}
