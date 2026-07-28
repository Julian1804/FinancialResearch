import { setResultPanel } from "./ai-bridge.js";
import { workspaceApi } from "./api.js";
import { escapeHtml, head } from "./components.js";
import { renderSqlExplorerPage } from "./database-browser.js";
import { lang } from "./i18n.js";

let catalogState = {
  payload: null,
  selectedCategory: "trading",
  selectedProduct: "",
  search: "",
  loading: false,
  error: "",
};

const COPY = {
  zh: {
    kicker: "\u6570\u636e\u5e93",
    title: "\u6570\u636e\u76ee\u5f55",
    subtitle: "\u6309\u4f7f\u7528\u573a\u666f\u67e5\u770b FR \u5f53\u524d\u53ef\u7528\u7684\u6570\u636e\u3001\u8986\u76d6\u5bf9\u8c61\u3001\u65f6\u95f4\u8303\u56f4\u3001\u6765\u6e90\u548c\u8d28\u91cf\u8bf4\u660e\u3002",
    availableData: "\u53ef\u7528\u6570\u636e",
    search: "\u641c\u7d22\u6807\u7684\u3001\u6307\u6807\u3001\u6570\u636e\u6e90\u6216\u4e3b\u9898",
    products: "\u6570\u636e\u4ea7\u54c1",
    product: "\u6570\u636e\u4ea7\u54c1",
    category: "\u5206\u7c7b",
    coverage: "\u8986\u76d6\u5bf9\u8c61",
    records: "\u8bb0\u5f55\u6570",
    fields: "\u5b57\u6bb5\u6570",
    dateRange: "\u65f6\u95f4\u8303\u56f4",
    latestDate: "\u6700\u65b0\u6570\u636e\u65e5\u671f",
    latestUpdate: "\u6700\u8fd1\u66f4\u65b0\u65f6\u95f4",
    frequency: "\u6570\u636e\u9891\u7387",
    source: "\u6570\u636e\u6765\u6e90",
    fieldsAndSamples: "\u53ef\u67e5\u770b\u5b57\u6bb5\u548c\u6837\u4f8b",
    quality: "\u8d28\u91cf\u8bf4\u660e",
    openSql: "\u5728\u6570\u636e\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00",
    noSql: "\u5f53\u524d\u4ea7\u54c1\u5c1a\u65e0\u53ef\u6df1\u5165\u7684 SQL \u8868",
    advanced: "\u9ad8\u7ea7\u8bca\u65ad",
    noProducts: "\u5f53\u524d\u5206\u7c7b\u6ca1\u6709\u5df2\u843d\u5e93\u7684\u6570\u636e\u4ea7\u54c1\u3002",
    selectProduct: "\u9009\u62e9\u6570\u636e\u4ea7\u54c1\u67e5\u770b\u8986\u76d6\u3001\u5b57\u6bb5\u3001\u65f6\u95f4\u8303\u56f4\u548c\u8d28\u91cf\u8bf4\u660e\u3002",
    loading: "\u6b63\u5728\u52a0\u8f7d\u53ef\u7528\u6570\u636e\u76ee\u5f55\u2026",
    loadError: "\u6570\u636e\u76ee\u5f55\u6682\u65f6\u65e0\u6cd5\u52a0\u8f7d\uff0c\u8bf7\u68c0\u67e5\u540e\u7aef\u670d\u52a1\u540e\u91cd\u8bd5\u3002",
    publicationNote: "\u65e5\u671f\u8bf4\u660e",
    examples: "\u793a\u4f8b\u5bf9\u8c61",
    status: "\u6570\u636e\u72b6\u6001",
    categoryCount: "\u6570\u636e\u5206\u7c7b",
    productCount: "\u6570\u636e\u4ea7\u54c1",
    recordCount: "\u5df2\u843d\u5e93\u8bb0\u5f55",
    latestAvailable: "\u6700\u65b0\u6570\u636e",
    dataLayer: "\u6570\u636e\u5c42",
    metricCount: "\u6307\u6807\u6570\u91cf",
    observationProducts: "\u89c2\u5bdf\u6570\u636e\u4ea7\u54c1",
    referenceProducts: "\u53c2\u8003 / \u4e3b\u6570\u636e\u4ea7\u54c1",
    grain: "\u7c92\u5ea6",
    coverageScope: "\u8986\u76d6\u8303\u56f4",
    searchResults: "\u641c\u7d22\u7ed3\u679c",
    dataName: "\u6570\u636e\u540d\u79f0",
    unavailable: "\u6682\u672a\u5165\u5e93",
    plannedRequirement: "\u4e0b\u4e00\u6570\u636e\u6e90\u8981\u6c42",
    viewFieldsSamples: "\u67e5\u770b\u5b57\u6bb5\u548c\u6837\u4f8b",
  },
  en: {
    kicker: "Database",
    title: "Data Catalog",
    subtitle: "Explore currently available FR data, covered objects, date ranges, sources, and quality notes by research use.",
    availableData: "Available Data",
    search: "Search instruments, indicators, sources, or topics",
    products: "Data Products",
    product: "Data Product",
    category: "Category",
    coverage: "Coverage",
    records: "Records",
    fields: "Fields",
    dateRange: "Date Range",
    latestDate: "Latest Data Date",
    latestUpdate: "Latest Update Time",
    frequency: "Frequency",
    source: "Data Source",
    fieldsAndSamples: "Fields and samples available",
    quality: "Quality Notes",
    openSql: "Open in Data Explorer",
    noSql: "No linked SQL table is available for this product yet",
    advanced: "Advanced diagnostics",
    noProducts: "No landed data products in this category.",
    selectProduct: "Select a data product to review coverage, fields, date range, and quality notes.",
    loading: "Loading available data catalog\u2026",
    loadError: "The Data Catalog is temporarily unavailable. Check the backend service and try again.",
    publicationNote: "Date Note",
    examples: "Example Objects",
    status: "Data Status",
    categoryCount: "Data Categories",
    productCount: "Data Products",
    recordCount: "Landed Records",
    latestAvailable: "Latest Data",
    dataLayer: "Data Layer",
    metricCount: "Metrics",
    observationProducts: "Observation Products",
    referenceProducts: "Reference / Master Products",
    grain: "Grain",
    coverageScope: "Coverage Scope",
    searchResults: "Search Results",
    dataName: "Data Name",
    unavailable: "Not available yet",
    plannedRequirement: "Next data-source requirement",
    viewFieldsSamples: "View fields and samples",
  },
};

function copy() {
  return COPY[lang()] || COPY.zh;
}

function value(input, fallback = "") {
  return escapeHtml(input === undefined || input === null || input === "" ? fallback : String(input));
}

function number(input) {
  return new Intl.NumberFormat(lang() === "en" ? "en-US" : "zh-CN").format(Number(input || 0));
}

function productName(product) {
  return lang() === "en" ? product.display_name_en : product.display_name_zh;
}

function categoryName(category) {
  return lang() === "en" ? category.en : category.zh;
}

function sourceName(product) {
  return lang() === "en" ? (product.source_display_name_en || product.source_display_name) : product.source_display_name;
}

function frequencyName(product) {
  return lang() === "en" ? (product.frequency_en || product.frequency) : (product.frequency_zh || product.frequency);
}

function coverageSummary(product) {
  return lang() === "en" ? product.coverage_summary_en : product.coverage_summary_zh;
}

function observationGrain(product) {
  return lang() === "en" ? product.observation_grain_en : product.observation_grain_zh;
}

function coverageScope(product) {
  return lang() === "en" ? product.coverage_scope_en : product.coverage_scope_zh;
}

function dataLayerName(product) {
  return lang() === "en" ? product.data_layer_en : product.data_layer_zh;
}

function selectedProduct() {
  return (catalogState.payload?.products || []).find((row) => row.data_product_id === catalogState.selectedProduct) || null;
}

function filteredProducts() {
  const products = catalogState.payload?.products || [];
  const query = catalogState.search.trim().toLowerCase();
  return products.filter((product) => {
    if (!query && product.user_category !== catalogState.selectedCategory) return false;
    if (!query) return true;
    const searchable = [
      product.display_name_zh,
      product.display_name_en,
      product.user_category_zh,
      product.user_category_en,
      product.sub_category,
      product.source_display_name,
      product.source_display_name_en,
      ...(product.available_fields_summary || []),
      ...(product.example_entities || []),
    ].join(" ").toLowerCase();
    return searchable.includes(query);
  });
}

function normalizedQuery() {
  return catalogState.search.trim().toLowerCase();
}

function searchResults() {
  const query = normalizedQuery();
  if (!query) return [];
  const rows = catalogState.payload?.entity_search_index || [];
  return rows.filter((row) => {
    const aliases = (row.query_aliases || []).join(" ").toLowerCase();
    const searchable = [
      aliases,
      row.display_name_zh,
      row.display_name_en,
      row.data_name_zh,
      row.data_name_en,
      row.category_zh,
      row.category_en,
      row.coverage_zh,
      row.coverage_en,
      row.source_zh,
      row.source_en,
      row.quality_zh,
      row.quality_en,
    ].join(" ").toLowerCase();
    return searchable.includes(query);
  }).slice(0, 8);
}

function categoriesHtml() {
  const categories = catalogState.payload?.categories || [];
  return `<section class="catalog-category-grid" aria-label="${escapeHtml(copy().availableData)}">
    ${categories.map((category) => `<button class="catalog-category-card ${category.id === catalogState.selectedCategory && !catalogState.search ? "active" : ""} ${category.support ? "support" : ""}" data-catalog-category="${value(category.id)}">
      <strong>${escapeHtml(categoryName(category))}</strong>
      <span>${number(category.data_product_count)}</span>
    </button>`).join("")}
  </section>`;
}

function catalogOverview() {
  const c = copy();
  const categories = catalogState.payload?.categories || [];
  const products = catalogState.payload?.products || [];
  const available = products.filter((product) => Number(product.record_count || 0) > 0);
  const records = available.reduce((total, product) => total + Number(product.record_count || 0), 0);
  const latest = available.map((product) => product.latest_data_date).filter(Boolean).sort().at(-1) || "-";
  const observationCount = available.filter((product) => product.data_layer === "observation_time_series").length;
  const referenceCount = available.filter((product) => product.data_layer === "reference_master").length;
  return `<section class="connections-metrics" data-catalog-overview>
    <span><b>${escapeHtml(c.categoryCount)}</b>${number(categories.length)}</span>
    <span><b>${escapeHtml(c.productCount)}</b>${number(available.length)}</span>
    <span><b>${escapeHtml(c.observationProducts)}</b>${number(observationCount)}</span>
    <span><b>${escapeHtml(c.referenceProducts)}</b>${number(referenceCount)}</span>
    <span><b>${escapeHtml(c.recordCount)}</b>${number(records)}</span>
    <span><b>${escapeHtml(c.latestAvailable)}</b>${value(latest)}</span>
  </section>`;
}

function productRows() {
  const c = copy();
  const rows = filteredProducts();
  if (!rows.length) return `<div class="empty">${escapeHtml(c.noProducts)}</div>`;
  return `<div class="catalog-product-list" data-catalog-product-list>
    ${rows.map((product) => `<button class="catalog-product-row ${product.data_product_id === catalogState.selectedProduct ? "active" : ""}" data-catalog-product="${value(product.data_product_id)}">
      <span class="catalog-product-name"><strong>${value(productName(product))}</strong><small>${value(dataLayerName(product))} · ${value(coverageSummary(product) || (lang() === "en" ? product.user_category_en : product.user_category_zh))}</small></span>
      <span><b>${escapeHtml(c.records)}</b>${number(product.record_count)}</span>
      <span><b>${escapeHtml(c.latestDate)}</b>${value(product.latest_data_date, "-")}</span>
      <span><b>${escapeHtml(c.source)}</b>${value(sourceName(product), "-")}</span>
    </button>`).join("")}
  </div>`;
}

function searchResultCards() {
  const c = copy();
  const rows = searchResults();
  if (!catalogState.search.trim()) return "";
  if (!rows.length) {
    return `<section class="catalog-search-results"><h2>${escapeHtml(c.searchResults)}</h2><div class="empty">${escapeHtml(c.unavailable)}</div></section>`;
  }
  return `<section class="catalog-search-results" data-entity-search-results>
    <h2>${escapeHtml(c.searchResults)}</h2>
    <div class="summary-card-grid">
      ${rows.map((row) => {
        const dataName = lang() === "en" ? row.data_name_en : row.data_name_zh;
        const status = lang() === "en" ? row.status_label_en : row.status_label_zh;
        const coverage = lang() === "en" ? row.coverage_en : row.coverage_zh;
        const source = lang() === "en" ? row.source_en : row.source_zh;
        const quality = lang() === "en" ? row.quality_en : row.quality_zh;
        const requirement = lang() === "en" ? (row.planned_requirement_en || row.source_en) : (row.planned_requirement_zh || row.source_zh);
        const linked = row.product_id ? `<button class="btn secondary" data-search-product="${value(row.product_id)}">${escapeHtml(c.viewFieldsSamples)}</button>` : "";
        const sql = row.open_in_sql_browser_target ? `<button class="btn primary" data-search-sql="${value(row.product_id)}">${escapeHtml(c.openSql)}</button>` : "";
        return `<article class="card catalog-search-card" data-entity-search-result data-search-status="${value(row.status)}">
          <h3>${value(dataName)}</h3>
          <span class="tag ${row.status === "planned_not_available" || row.status === "missing" ? "warn" : "ok"}">${value(status)}</span>
          <dl class="catalog-product-facts">
            ${fact(c.coverage, coverage)}
            ${fact(c.records, number(row.record_count))}
            ${fact(c.fields, number(row.field_count))}
            ${fact(c.dateRange, row.date_range)}
            ${fact(c.latestDate, row.latest_data_date)}
            ${fact(c.latestUpdate, row.latest_update_time)}
            ${fact(c.source, source)}
            ${row.status === "planned_not_available" || row.status === "missing" ? fact(c.plannedRequirement, requirement || c.unavailable) : ""}
            ${fact(c.quality, quality)}
          </dl>
          <div class="actions">${linked}${sql}</div>
        </article>`;
      }).join("")}
    </div>
  </section>`;
}

function fact(label, item, fallback = "-") {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${value(item, fallback)}</dd></div>`;
}

function productDetail() {
  const c = copy();
  const product = selectedProduct();
  if (!product) return `<section class="catalog-product-detail empty">${escapeHtml(c.selectProduct)}</section>`;
  const dateRange = `${product.date_min || "-"} \u2192 ${product.date_max || "-"}`;
  const publishNote = product.publish_date_user_label_zh || product.publish_date_user_label_en
    ? fact(c.publicationNote, lang() === "en" ? product.publish_date_user_label_en : product.publish_date_user_label_zh)
    : "";
  const examples = (product.example_entities || []).join(", ");
  const fields = (lang() === "en" ? (product.available_fields_summary_en || product.available_fields_summary) : product.available_fields_summary || []).map((field) => `<span>${value(field)}</span>`).join("");
  const sqlAction = product.open_in_sql_browser_target
    ? `<button class="btn primary" data-open-product-sql="${value(product.data_product_id)}">${escapeHtml(c.openSql)}</button>`
    : `<span class="muted">${escapeHtml(c.noSql)}</span>`;
  return `<section class="catalog-product-detail" data-catalog-product-detail>
    <div class="catalog-product-detail-head">
      <div><div class="eyebrow">${escapeHtml(c.product)}</div><h2>${value(productName(product))}</h2></div>
      <span class="tag ${product.record_count ? "ok" : "warn"}">${value(lang() === "en" ? product.data_status_label_en : product.data_status_label_zh)}</span>
    </div>
    <p class="catalog-coverage-copy">${value(coverageSummary(product))}</p>
    <dl class="catalog-product-facts">
      ${fact(c.category, lang() === "en" ? product.user_category_en : product.user_category_zh)}
      ${dataLayerName(product) ? fact(c.dataLayer, dataLayerName(product)) : ""}
      ${fact(c.coverage, number(product.supported_entity_count))}
      ${product.metric_count !== undefined ? fact(c.metricCount, number(product.metric_count)) : ""}
      ${fact(c.records, number(product.record_count))}
      ${fact(c.fields, number(product.field_count))}
      ${fact(c.frequency, frequencyName(product))}
      ${observationGrain(product) ? fact(c.grain, observationGrain(product)) : ""}
      ${coverageScope(product) ? fact(c.coverageScope, coverageScope(product)) : ""}
      ${fact(c.dateRange, dateRange)}
      ${fact(c.latestDate, product.latest_data_date)}
      ${fact(c.latestUpdate, product.latest_update_time)}
      ${fact(c.source, sourceName(product))}
      ${examples ? fact(c.examples, examples) : ""}
      ${publishNote}
    </dl>
    <section class="catalog-field-summary"><h3>${escapeHtml(c.fieldsAndSamples)}</h3><div>${fields}</div></section>
    <section class="catalog-quality-note"><h3>${escapeHtml(c.quality)}</h3><p>${value(lang() === "en" ? product.user_warning_summary_en : product.user_warning_summary_zh)}</p></section>
    <div class="actions">${sqlAction}</div>
  </section>`;
}

function advancedDiagnostics() {
  const c = copy();
  const selected = selectedProduct();
  return `<details class="catalog-advanced" data-catalog-advanced>
    <summary>${escapeHtml(c.advanced)}</summary>
    <pre>${escapeHtml(JSON.stringify({
      catalog: catalogState.payload?.developer_diagnostics || {},
      selected_product: selected?.developer_metadata || {},
      sql_target: selected?.open_in_sql_browser_target || null,
    }, null, 2))}</pre>
  </details>`;
}

function bridgeProduct() {
  const c = copy();
  const product = selectedProduct();
  if (!product) {
    setResultPanel("database", {
      title: c.availableData,
      eyebrow: c.title,
      summary: c.selectProduct,
      statusText: c.status,
      html: `<div class="result-empty">${escapeHtml(c.selectProduct)}</div>`,
    });
    return;
  }
  const publishNote = product.publish_date_user_label_zh || product.publish_date_user_label_en
    ? fact(c.publicationNote, lang() === "en" ? product.publish_date_user_label_en : product.publish_date_user_label_zh)
    : "";
  setResultPanel("database", {
    title: productName(product),
    eyebrow: c.availableData,
    summary: coverageSummary(product),
    statusText: lang() === "en" ? product.data_status_label_en : product.data_status_label_zh,
    html: `<section class="catalog-bridge-summary" data-catalog-bridge-summary><h3>${escapeHtml(c.availableData)}</h3><dl>
      ${fact(c.category, lang() === "en" ? product.user_category_en : product.user_category_zh)}
      ${fact(c.records, number(product.record_count))}
      ${fact(c.fields, number(product.field_count))}
      ${observationGrain(product) ? fact(c.grain, observationGrain(product)) : ""}
      ${coverageScope(product) ? fact(c.coverageScope, coverageScope(product)) : ""}
      ${fact(c.dateRange, `${product.date_min || "-"} \u2192 ${product.date_max || "-"}`)}
      ${fact(c.latestDate, product.latest_data_date)}
      ${fact(c.source, sourceName(product))}
      ${publishNote}
    </dl></section>`,
  });
}

function render() {
  const c = copy();
  const root = document.getElementById("workspace-main");
  if (!root) return;
  root.innerHTML = `<div class="page user-data-catalog" data-user-data-catalog-primary>
    ${head(c.kicker, c.title, c.subtitle)}
    ${catalogState.error ? `<div class="risk">${escapeHtml(c.loadError)}</div>` : ""}
    <label class="catalog-search"><span>${escapeHtml(c.search)}</span><input class="input" type="search" value="${value(catalogState.search)}" placeholder="${escapeHtml(c.search)}" data-catalog-search></label>
    ${catalogState.loading ? "" : catalogOverview()}
    ${catalogState.loading ? `<div class="empty">${escapeHtml(c.loading)}</div>` : categoriesHtml()}
    ${searchResultCards()}
    <section class="catalog-workspace">
      <div class="catalog-products-pane"><div class="section-head"><div><h2>${escapeHtml(c.products)}</h2><p>${number(filteredProducts().length)} ${escapeHtml(c.availableData)}</p></div></div>${productRows()}</div>
      ${productDetail()}
    </section>
    ${advancedDiagnostics()}
  </div>`;
  bind();
}

function chooseFirstProduct() {
  const rows = filteredProducts();
  catalogState.selectedProduct = rows[0]?.data_product_id || "";
}

function bind() {
  document.querySelectorAll("[data-catalog-category]").forEach((button) => {
    button.onclick = () => {
      catalogState.selectedCategory = button.dataset.catalogCategory;
      catalogState.search = "";
      chooseFirstProduct();
      render();
      bridgeProduct();
    };
  });
  document.querySelectorAll("[data-catalog-product]").forEach((button) => {
    button.onclick = () => {
      catalogState.selectedProduct = button.dataset.catalogProduct;
      render();
      bridgeProduct();
    };
  });
  document.querySelector("[data-catalog-search]")?.addEventListener("input", (event) => {
    catalogState.search = event.target.value;
    chooseFirstProduct();
    render();
    bridgeProduct();
    const input = document.querySelector("[data-catalog-search]");
    input?.focus();
    input?.setSelectionRange(input.value.length, input.value.length);
  });
  document.querySelector("[data-open-product-sql]")?.addEventListener("click", () => {
    const target = selectedProduct()?.open_in_sql_browser_target;
    if (target) renderSqlExplorerPage({ initialTarget: target });
  });
  document.querySelectorAll("[data-search-product]").forEach((button) => {
    button.onclick = () => {
      catalogState.selectedProduct = button.dataset.searchProduct || "";
      render();
      bridgeProduct();
    };
  });
  document.querySelectorAll("[data-search-sql]").forEach((button) => {
    button.onclick = () => {
      const product = (catalogState.payload?.products || []).find((row) => row.data_product_id === button.dataset.searchSql);
      const target = product?.open_in_sql_browser_target;
      if (target) renderSqlExplorerPage({ initialTarget: target });
    };
  });
}

export async function renderUserDataCatalogPage() {
  catalogState = { ...catalogState, payload: null, selectedCategory: "trading", selectedProduct: "", search: "", loading: true, error: "" };
  bridgeProduct();
  render();
  try {
    const payload = await workspaceApi.researchWorkspace.userDataCatalog();
    catalogState = { ...catalogState, payload, loading: false };
    catalogState.selectedProduct = filteredProducts()[0]?.data_product_id || "";
    render();
    bridgeProduct();
  } catch (error) {
    catalogState = { ...catalogState, loading: false, error: error.message || String(error) };
    render();
  }
}
