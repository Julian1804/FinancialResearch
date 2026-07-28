import { failOperationPanel, finishOperationPanel, setWorkbenchBridge, startOperationPanel } from "../ai-bridge.js";
import { escapeHtml, head } from "../components.js";
import { formatAssetCategory, formatFieldName, formatFrequency, formatSourceName, formatUnit } from "../display-model.js";
import { lang, tx } from "../i18n.js";

const INTERNAL_WORKBENCH_DATASET = "object_bound_feature_instance_set";

const backendModelRegistrySource = "/api/modeling-workbench/options";

const L = {
  zh: {
    all: "全部",
    asset: "资产",
    field: "字段",
    frequency: "频率",
    unit: "单位",
    searchPlaceholder: "搜索可见名称或技术 ID",
    source: "来源",
    setY: "设为因变量",
    addX: "加入 X",
    remove: "移除",
    moveUp: "上移",
    moveDown: "下移",
    yUnsupported: "当前字段不支持作为因变量",
    noFactors: "没有匹配的因子。",
    y: "因变量 Y",
    x: "自变量 X",
    count: "数量",
    noX: "尚未选择 X。",
    samplePreset: "样本预设",
    sampleConnected: "样本筛选状态",
    sampleBlocker: "手动样本筛选尚未接入后端；预览会把请求参数发给后端，并等待后端回显。",
    selectedOnly: "仅显示已选资产",
    manualSupported: "手动筛选支持",
    notSupported: "不支持",
    standardization: "标准化",
    missingPolicy: "缺失值处理",
    rollingEnabled: "启用滚动窗口",
    rollingWindow: "滚动窗口",
    previewStatus: "预览已启动",
    runStatus: "运行已启动",
    previewDone: "预览已完成",
    runDone: "运行已完成",
    previewTarget: "建模预览请求",
    runTarget: "诊断运行请求",
    validate: "校验可见变量",
    coverage: "检查数据覆盖",
    summary: "计算摘要统计",
    finalSample: "生成最终样本说明",
    submitRun: "提交运行请求",
    waitRun: "等待后端诊断执行",
    readRun: "读取模型结果",
    renderRun: "渲染输出",
    realRows: "真实后端行",
    exactBlocker: "精确原因",
    backendEcho: "后端回显",
    ignoredSelection: "后端未回显或未识别的可见选择",
    none: "无",
    finalSampleBlocker: "最终样本暂不可用：预览接口未返回最终样本或样本摘要，不能用前端选择推导资产数、日期范围或样本量。",
    runResultBlocker: "模型结果暂不可用：运行接口未返回模型摘要、系数或样本量。",
    historyBlocker: "历史记录暂不可用：运行接口未返回后端历史；不会用本地时间伪造历史记录。",
    chartBlocker: "图表暂不可用：运行接口未返回可渲染图表数据。",
    summaryBlocker: "摘要统计暂不可用：预览接口没有返回摘要统计，也没有返回可计算统计量的有界样本值。",
    dateRange: "日期范围",
    requestedSample: "请求样本筛选",
    effectiveY: "有效 Y",
    xList: "X 列表",
    modelFamily: "模型族",
    payload: "请求内容",
    blockers: "限制说明",
    status: "状态",
    diagnosticOnly: "仅诊断",
    productionWrite: "生产写入",
    modelObjectScope: "模型对象范围",
    panelGrain: "样本粒度",
    joinKeys: "连接键",
    universeLabel: "对象宇宙",
    entityCount: "对象数",
    dateCount: "日期数",
    sampleRowCount: "样本行数",
    targetIdentity: "因变量对象身份",
    featureIdentities: "自变量对象身份",
  },
  en: {
    all: "All",
    asset: "Asset",
    field: "Field",
    frequency: "Frequency",
    unit: "Unit",
    searchPlaceholder: "Search visible labels or technical IDs",
    source: "Source",
    setY: "Set as Y",
    addX: "Add as X",
    remove: "Remove",
    moveUp: "Move up",
    moveDown: "Move down",
    yUnsupported: "This field is not supported as Y",
    noFactors: "No matching factors.",
    y: "Dependent variable Y",
    x: "Independent variables X",
    count: "count",
    noX: "No X variables selected.",
    samplePreset: "Sample preset",
    sampleConnected: "Sample filter status",
    sampleBlocker: "Manual sample filtering is not connected to backend yet. Preview sends the request and waits for backend echo.",
    selectedOnly: "Show selected assets only",
    manualSupported: "Manual filter supported",
    notSupported: "false",
    standardization: "Standardization",
    missingPolicy: "Missing policy",
    rollingEnabled: "Enable rolling window",
    rollingWindow: "Rolling window",
    previewStatus: "Preview started",
    runStatus: "Run started",
    previewDone: "Preview completed",
    runDone: "Run completed",
    previewTarget: "Modeling preview request",
    runTarget: "Diagnostic run request",
    validate: "Validate visible variables",
    coverage: "Check data coverage",
    summary: "Compute summary statistics",
    finalSample: "Generate final sample note",
    submitRun: "Submit run request",
    waitRun: "Wait for backend diagnostic execution",
    readRun: "Read model result",
    renderRun: "Render output",
    realRows: "real backend rows",
    exactBlocker: "exact blocker",
    backendEcho: "Backend echo",
    ignoredSelection: "Visible selections not echoed or recognized by backend",
    none: "none",
    finalSampleBlocker: "Final sample is unavailable: Preview API did not return backend-backed final_sample or sample_summary, so frontend selections cannot be used to infer asset count, date range, or sample size.",
    runResultBlocker: "Model result is unavailable: Run API did not return a model summary, coefficients, or sample size.",
    historyBlocker: "History is unavailable: Run API did not return backend-backed history; local timestamps are not used as run history.",
    chartBlocker: "Charts are unavailable: Run API did not return renderable chart/plot payload.",
    summaryBlocker: "Summary statistics are unavailable because model execution is not connected.",
    dateRange: "Date range",
    requestedSample: "Requested sample filter",
    effectiveY: "Effective Y",
    xList: "X list",
    modelFamily: "Model family",
    payload: "Request payload",
    blockers: "Limits",
    status: "Status",
    diagnosticOnly: "Diagnostic only",
    productionWrite: "Production write",
    modelObjectScope: "Model object scope",
    panelGrain: "Panel grain",
    joinKeys: "Join keys",
    universeLabel: "Universe",
    entityCount: "Entity count",
    dateCount: "Date count",
    sampleRowCount: "Sample rows",
    targetIdentity: "Target object identity",
    featureIdentities: "Feature object identities",
  },
};

const labelMaps = {
  asset: {
    all: { zh: "全部", en: "All" },
    a_share: { zh: "A股", en: "A-share" },
    hk: { zh: "港股", en: "HK" },
    etf: { zh: "ETF", en: "ETF" },
    index: { zh: "指数", en: "Index" },
    fx: { zh: "外汇", en: "FX" },
    rates_bonds: { zh: "利率/债券", en: "Rates/Bonds" },
    commodities: { zh: "商品/期货", en: "Commodities" },
    macro: { zh: "宏观", en: "Macro" },
    events: { zh: "事件", en: "Events" },
  },
  field: {
    all: { zh: "全部", en: "All" },
    close: { zh: "收盘价", en: "Close" },
    amount: { zh: "成交额", en: "Amount" },
    volume: { zh: "成交量", en: "Volume" },
    return: { zh: "收益率", en: "Return" },
    market_cap: { zh: "市值", en: "Market cap" },
    nav: { zh: "NAV", en: "NAV" },
    shares: { zh: "份额", en: "Shares" },
    fx_rate: { zh: "汇率", en: "FX rate" },
    yield: { zh: "收益率/利率", en: "Yield" },
    commodity_price: { zh: "商品价格", en: "Commodity price" },
    macro: { zh: "宏观", en: "Macro" },
    event: { zh: "事件", en: "Event" },
  },
  frequency: {
    all: { zh: "全部", en: "All" },
    daily: { zh: "日频", en: "Daily" },
    weekly: { zh: "周频", en: "Weekly" },
    monthly: { zh: "月频", en: "Monthly" },
    report_period: { zh: "报告期", en: "Report period" },
    event: { zh: "事件", en: "Event" },
  },
};

const assetRows = [
  { code: "600519", market: "a_share" },
  { code: "000001", market: "a_share" },
  { code: "300750", market: "a_share" },
  { code: "510300", market: "etf" },
  { code: "159919", market: "etf" },
];

Object.assign(L.zh, {
  searchPlaceholder: "\u641c\u7d22\u53ef\u89c1\u540d\u79f0",
  sampleBlocker: "\u624b\u52a8\u6837\u672c\u7b5b\u9009\u5c1a\u672a\u63a5\u5165\uff1b\u9884\u89c8\u4f1a\u4f7f\u7528\u5f53\u524d\u53ef\u89c1\u9009\u62e9\u3002",
  waitRun: "\u7b49\u5f85\u8bca\u65ad\u6267\u884c",
  realRows: "\u6709\u754c\u6837\u672c\u884c",
  backendEcho: "\u9009\u62e9\u6838\u5bf9",
  ignoredSelection: "\u90e8\u5206\u53ef\u89c1\u9009\u62e9\u672a\u5728\u7ed3\u679c\u4e2d\u786e\u8ba4",
  finalSampleBlocker: "\u6700\u7ec8\u6837\u672c\u6682\u4e0d\u53ef\u7528\uff1a\u672c\u6b21\u9884\u89c8\u672a\u8fd4\u56de\u6709\u754c\u6837\u672c\u6458\u8981\u3002",
  historyBlocker: "\u5386\u53f2\u8bb0\u5f55\u6682\u4e0d\u53ef\u7528\uff1a\u672c\u6b21\u8bca\u65ad\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u5386\u53f2\u884c\u3002",
  chartBlocker: "\u56fe\u8868\u6682\u4e0d\u53ef\u7528\uff1a\u672c\u6b21\u8bca\u65ad\u6ca1\u6709\u53ef\u6e32\u67d3\u7684\u56fe\u8868\u6570\u636e\u3002",
  summaryBlocker: "\u6458\u8981\u7edf\u8ba1\u6682\u4e0d\u53ef\u7528\uff1a\u672c\u6b21\u9884\u89c8\u6ca1\u6709\u53ef\u5c55\u793a\u7684\u6709\u754c\u6837\u672c\u7edf\u8ba1\u3002",
  payload: "\u8bf7\u6c42\u6458\u8981",
});
Object.assign(L.en, {
  searchPlaceholder: "Search visible labels",
  sampleBlocker: "Manual sample filtering is not connected yet. Preview uses the current visible selection.",
  waitRun: "Wait for diagnostic execution",
  realRows: "catalog variables checked",
  backendEcho: "Selection check",
  ignoredSelection: "Some visible selections were not confirmed in the result",
  finalSampleBlocker: "An analysis sample is unavailable because model execution is not connected.",
  historyBlocker: "History is unavailable: this diagnostic has no displayable history rows.",
  chartBlocker: "Charts are unavailable: this diagnostic did not return renderable chart data.",
  summaryBlocker: "Summary statistics are unavailable because model execution is not connected.",
  payload: "Request summary",
});

let filters = { asset: "all", field: "all", unit: "all", frequency: "all", search: "" };
let selectedY = "stock_return_1d";
let selectedX = ["stock_amount", "stock_volume", "stock_turnover_rate", "stock_close_to_ma20"];
let selectedAssets = new Set(["600519", "000001", "300750"]);
let showSelectedAssetsOnly = false;
let advancedOpen = false;
let rollingEnabled = false;
let modelType = "ols";
let workbenchControls = {
  date_start: "2025-06-19",
  date_end: "2026-06-18",
  frequency: "daily",
  rolling_window: 20,
  standardization: "z_score",
  missing_policy: "inner_join_aligned_dates",
};
let previewInFlight = false;
let backendOptions = null;
let backendOptionsLoading = false;
let backendOptionsError = "";

function local() {
  return L[lang()] || L.zh;
}

function normalizeFactor(row) {
  const id = row.model_variable_id || row.id || row.feature_id || "";
  const technicalDiagnostic = /missing|rolling|volatility|flag/i.test(id);
  return {
    id,
    model_variable_id: id,
    label: row.label || { zh: row.display_name_zh || row.display_label_zh || formatFieldName(id, "zh"), en: row.display_name_en || row.display_label_en || formatFieldName(id, "en") },
    display_label_zh: row.display_name_zh || row.display_label_zh || row.label?.zh || formatFieldName(id, "zh"),
    display_label_en: row.display_name_en || row.display_label_en || row.label?.en || formatFieldName(id, "en"),
    asset: row.asset || row.entity_type || "model_variable",
    field: row.field || row.transform_type || id,
    frequency: row.frequency || "daily",
    unit: row.unit || "",
    source: row.source || row.derived_from_data_product_id || "model_variable_catalog",
    y: row.usable_as_y === true || row.y === true,
    usable_as_x: row.usable_as_x !== false,
    proxy: row.proxy === true || technicalDiagnostic,
    object_type: row.object_type || "",
    object_scope: row.object_scope || row.entity_scope || "",
    object_universe_label: row.object_universe_label || "",
    panel_grain: row.model_grain || row.panel_grain || "",
    model_grain: row.model_grain || row.panel_grain || "",
    entity_scope: row.entity_scope || row.object_scope || "",
    formula_zh: row.formula_zh || "",
    formula_en: row.formula_en || "",
    transform_type: row.transform_type || "",
    aggregation_method: row.aggregation_method || "",
    weighting_method: row.weighting_method || "",
    lag_policy: row.lag_policy || "",
    forward_shift_policy: row.forward_shift_policy || "",
    timing_policy: row.timing_policy || "",
    usable_as_y: row.usable_as_y === true,
    derived_from_data_product_id: row.derived_from_data_product_id || "",
    date_min: row.date_min || "",
    date_max: row.date_max || "",
    latest_data_date: row.latest_data_date || "",
    entity_count: row.entity_count || 0,
    availability_status: row.availability_status || "",
    blocker_if_not_usable: row.blocker_if_not_usable || "",
    join_keys: row.join_keys || [],
    entity_id_policy: row.entity_id_policy || "",
    source_trace: row.source_trace || {},
    scope_badge_zh: row.scope_badge_zh || "",
    scope_badge_en: row.scope_badge_en || "",
    missing_identity_blocker: row.missing_identity_blocker || "",
    ordinary_research_use: row.ordinary_research_use === true,
  };
}

function factorDisplayName(itemOrId) {
  const item = typeof itemOrId === "string" ? selectedFactor(itemOrId) : itemOrId;
  if (!item) return formatFieldName(String(itemOrId || ""), lang());
  return lang() === "en" ? (item.display_label_en || formatFieldName(item.id, "en")) : (item.display_label_zh || formatFieldName(item.id, "zh"));
}

function factorScopeBadge(item) {
  if (!item) return "";
  if (item.model_grain || item.entity_scope) return [item.model_grain, item.entity_scope, item.transform_type].filter(Boolean).join(" | ");
  const badge = lang() === "en" ? item.scope_badge_en : item.scope_badge_zh;
  if (badge) return badge;
  return [item.object_universe_label, item.panel_grain, item.unit].filter(Boolean).join(" | ");
}

function variableDisplayName(id) {
  if (id === "intercept") return formatFieldName(id, lang());
  return factorDisplayName(id);
}

function localizedScopeValue(value) {
  const raw = String(value || "");
  if (lang() === "en") return raw;
  const map = {
    asset_date: "个股-交易日",
    asset_id: "个股ID",
    panel_date: "交易日",
  };
  return map[raw] || raw;
}

function localizedIdentityName(row) {
  if (!row) return "";
  return lang() === "en"
    ? (row.display_label_en || factorDisplayName(row.factor_id || ""))
    : (row.display_label_zh || factorDisplayName(row.factor_id || ""));
}

function normalizeModel(row) {
  const id = row.id || row.model_id || "";
  return {
    id,
    label: row.label || id,
    enabled: row.enabled === true,
    reason: row.reason || row.status || "",
  };
}

function workbenchFactors() {
  return (backendOptions?.factor_registry || []).map(normalizeFactor).filter((item) => item.proxy !== true && item.usable_as_x !== false);
}

function workbenchModels() {
  return (backendOptions?.model_registry || backendOptions?.models || []).map(normalizeModel);
}

function backendOptionValues(key, field) {
  return ["all", ...new Set(workbenchFactors().map((item) => item[field]).filter(Boolean))];
}

function samplePresetOptions() {
  return backendOptions?.sample_presets?.length ? backendOptions.sample_presets : ["object_bound_default"];
}

function modelLabel(model) {
  const names = {
    descriptive_statistics: { zh: "描述统计", en: "Descriptive statistics" },
    correlation_matrix: { zh: "相关矩阵", en: "Correlation matrix" },
    ols: { zh: "普通最小二乘诊断", en: "OLS diagnostic" },
    rolling_ols: { zh: "滚动普通最小二乘", en: "Rolling OLS" },
    pca_factor_structure: { zh: "主成分因子结构", en: "PCA factor structure" },
    ridge: { zh: "岭回归", en: "Ridge regression" },
    lasso: { zh: "套索回归", en: "Lasso regression" },
    elastic_net: { zh: "弹性网络", en: "Elastic Net" },
    random_forest_diagnostic: { zh: "随机森林诊断", en: "Random forest diagnostic" },
    arima: { zh: "自回归移动平均", en: "ARIMA" },
    var: { zh: "向量自回归", en: "VAR" },
    regime_detection: { zh: "状态识别", en: "Regime detection" },
  };
  return names[model.id]?.[lang()] || label(model.label);
}

function modelReason(model) {
  if (lang() !== "en") {
    if (String(model.reason).includes("sklearn_missing")) return "依赖未安装";
    if (String(model.reason).includes("time_series")) return "时间序列预测暂不可用";
    if (String(model.reason).includes("not_connected")) return "适配器尚未接入";
    if (String(model.reason).includes("contract_not_connected")) return "运行契约尚未接入";
    return "暂未启用";
  }
  const reason = String(model.reason || "");
  if (reason.includes("sklearn_missing")) return "Dependency unavailable";
  if (reason.includes("time_series")) return "Time series forecast unavailable";
  if (reason.includes("not_connected")) return "Adapter not connected";
  if (reason.includes("contract_not_connected")) return "Run contract not connected";
  return "Not enabled";
}

function applyBackendOptionDefaults() {
  const factors = workbenchFactors();
  const models = workbenchModels();
  if (!selectedFactor(selectedY)) selectedY = backendOptions?.default_target || factors.find((item) => item.y)?.id || "";
  selectedX = selectedX.filter((id) => factors.some((item) => item.id === id));
  if (!selectedX.length) selectedX = (backendOptions?.default_features || factors.filter((item) => item.id !== selectedY).slice(0, 4).map((item) => item.id)).filter((id) => factors.some((item) => item.id === id));
  if (!models.some((model) => model.id === modelType && model.enabled)) modelType = models.find((model) => model.enabled)?.id || "ols";
}

async function loadBackendOptions() {
  if (backendOptions || backendOptionsLoading) return;
  backendOptionsLoading = true;
  backendOptionsError = "";
  try {
    const response = await fetch(backendModelRegistrySource);
    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) throw new Error(`${backendModelRegistrySource} ${response.status}`);
    if (!contentType.includes("application/json")) throw new Error(`${backendModelRegistrySource} returned non-JSON response`);
    const payload = await response.json();
    if (payload.status !== "ok" || !(payload.factor_registry || []).length) throw new Error("model_variable_catalog_unavailable");
    backendOptions = payload;
    applyBackendOptionDefaults();
  } catch (error) {
    backendOptions = null;
    backendOptionsError = "model_variable_catalog_unavailable";
  } finally {
    backendOptionsLoading = false;
    renderModelingWorkbench();
  }
}

function dateRangeText(start, end) {
  if (!start && !end) return "";
  return lang() === "en" ? `${start || ""} to ${end || ""}` : `${start || ""} 至 ${end || ""}`;
}

function visibleDateRangeText(value) {
  const raw = String(value || "");
  return lang() === "en" ? raw : raw.replace(/\s+to\s+/gi, " 至 ");
}

function currentYLabel() { return lang() === "en" ? "Current dependent variable" : "\u5f53\u524d\u56e0\u53d8\u91cf"; }
function addXLabel() { return lang() === "en" ? "Add as independent variable" : "\u6dfb\u52a0\u4e3a\u81ea\u53d8\u91cf"; }
function semanticLabels() {
  return lang() === "en"
    ? { library: "Model Variable Library", rawLink: "View raw data fields in Data Catalog / SQL Browser", formula: "Formula", grain: "Grain", scope: "Coverage Scope", transform: "Transform", timing: "Timing Policy", usable: "Usable as Y / X", sourceProduct: "Source data product", quality: "Quality", latest: "Latest Data Date", range: "Date Range", entityCount: "Entity Count", noRun: "Model execution is not available. Variable definitions can still be reviewed." }
    : { library: "\u6a21\u578b\u53d8\u91cf\u5e93", rawLink: "\u67e5\u770b\u539f\u59cb\u6570\u636e\u5b57\u6bb5\uff1a\u6570\u636e\u76ee\u5f55 / SQL \u6d4f\u89c8\u5668", formula: "\u516c\u5f0f", grain: "\u7c92\u5ea6", scope: "\u8986\u76d6\u5bf9\u8c61", transform: "\u53d8\u6362", timing: "\u65f6\u95f4\u653f\u7b56", usable: "\u53ef\u4f5c\u4e3a\u56e0\u53d8\u91cf / \u53ef\u4f5c\u4e3a\u81ea\u53d8\u91cf", sourceProduct: "\u6765\u6e90\u6570\u636e\u4ea7\u54c1", quality: "\u8d28\u91cf", latest: "\u6700\u65b0\u6570\u636e\u65e5\u671f", range: "\u65e5\u671f\u8303\u56f4", entityCount: "\u8986\u76d6\u5bf9\u8c61\u6570", noRun: "\u6a21\u578b\u6267\u884c\u5c1a\u672a\u5f00\u653e\uff0c\u4f46\u53ef\u4ee5\u67e5\u770b\u548c\u6838\u5bf9\u53d8\u91cf\u5b9a\u4e49\u3002" };
}

function semanticMetaRows(item) {
  const s = semanticLabels();
  const formula = lang() === "en" ? item.formula_en : item.formula_zh;
  return [
    [s.formula, formula],
    [s.grain, item.model_grain],
    [s.scope, item.entity_scope],
    [s.transform, item.transform_type],
    [s.timing, item.timing_policy || [item.lag_policy, item.forward_shift_policy].filter(Boolean).join("; ")],
    [s.usable, `${item.usable_as_y ? "Y" : "-"} / ${item.usable_as_x ? "X" : "-"}`],
    [s.range, dateRangeText(item.date_min, item.date_max)],
    [s.latest, item.latest_data_date],
    [s.entityCount, String(item.entity_count || 0)],
    [s.sourceProduct, item.derived_from_data_product_id],
    [s.quality, item.blocker_if_not_usable || item.availability_status || "usable"],
  ].filter((row) => row[1]);
}

function renderSemanticMeta(item, attrs = "") {
  return `<div class="variable-semantic-meta"${attrs}>${semanticMetaRows(item).map(([key, value]) => `<span><b>${escapeHtml(key)}</b>${escapeHtml(value)}</span>`).join("")}</div>`;
}

function label(value, type = null) {
  if (!value) return "";
  if (type === "asset") return formatAssetCategory(value, lang());
  if (type === "frequency") return formatFrequency(value, lang());
  if (type === "unit") return formatUnit(value, lang());
  if (type && labelMaps[type]?.[value]) return labelMaps[type][value][lang()] || labelMaps[type][value].en;
  if (typeof value === "object") return value[lang()] || value.en || value.zh || "";
  return String(value);
}

function selectedFactor(id) {
  return workbenchFactors().find((item) => item.id === id);
}

function yFactor() {
  return selectedFactor(selectedY);
}

function xFactors() {
  return selectedX.map(selectedFactor).filter(Boolean);
}

function table(headers, rows, attrs = "") {
  return `<table class="table"${attrs}><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function formatNumber(value, digits = 4) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value === null || value === undefined ? "" : String(value);
  return numeric.toLocaleString(lang() === "en" ? "en-US" : "zh-CN", { maximumFractionDigits: digits });
}

function formatRate(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value === null || value === undefined ? "" : String(value);
  const pct = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
  return `${pct.toLocaleString(lang() === "en" ? "en-US" : "zh-CN", { maximumFractionDigits: 2 })}%`;
}

function parseChartSpec(plot) {
  if (!plot?.chart_spec_json) return {};
  try { return JSON.parse(plot.chart_spec_json); } catch { return {}; }
}

function optionList(values, current, type = null) {
  return values.map((value) => `<option value="${escapeHtml(value)}"${value === current ? " selected" : ""}>${escapeHtml(type ? label(value, type) : formatUnit(value, lang()))}</option>`).join("");
}

function filteredFactors() {
  const query = filters.search.trim().toLowerCase();
  return workbenchFactors().filter((item) => {
    if (filters.asset !== "all" && item.asset !== filters.asset) return false;
    if (filters.field !== "all" && item.field !== filters.field) return false;
    if (filters.unit !== "all" && item.unit !== filters.unit) return false;
    if (filters.frequency !== "all" && item.frequency !== filters.frequency) return false;
    if (query) {
      const haystack = [
        item.id,
        item.label.zh,
        item.label.en,
        item.asset,
        item.field,
        item.frequency,
        item.unit,
        item.source,
        label(item.asset, "asset"),
        label(item.field, "field"),
        label(item.frequency, "frequency"),
      ].join(" ").toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

function renderFactorFilters() {
  const labels = tx("workbench");
  const ui = local();
  const backendAssetOptionValues = backendOptionValues("available_assets", "asset");
  const backendFieldOptionValues = backendOptionValues("available_fields", "field");
  const backendUnitOptionValues = backendOptionValues("available_units", "unit");
  const backendFrequencyOptionValues = backendOptionValues("available_frequencies", "frequency");
  return `<div class="factor-filter-grid" data-factor-filters>
    <label>${escapeHtml(labels.assetCategory || ui.asset)}<select class="input" data-factor-asset-filter>${optionList(backendAssetOptionValues, filters.asset, "asset")}</select></label>
    <label>${escapeHtml(labels.fieldFilter || ui.field)}<select class="input" data-factor-field-filter>${optionList(backendFieldOptionValues, filters.field, "field")}</select></label>
    <label>${escapeHtml(labels.unitFilter || ui.unit)}<select class="input" data-factor-unit-filter>${optionList(backendUnitOptionValues, filters.unit)}</select></label>
    <label>${escapeHtml(labels.frequencyFilter || ui.frequency)}<select class="input" data-factor-frequency-filter>${optionList(backendFrequencyOptionValues, filters.frequency, "frequency")}</select></label>
    <label>${escapeHtml(labels.search || "Search")}<input class="input" id="mw-factor-search" value="${escapeHtml(filters.search)}" placeholder="${escapeHtml(ui.searchPlaceholder)}"></label>
  </div>`;
}

function renderFactorLibrary() {
  const ui = local();
  const semantic = semanticLabels();
  const rows = filteredFactors();
  return `<div class="factor-browser" data-factor-browser>
    ${rows.map((item) => {
      const canSetY = item.y === true;
      const isX = selectedX.includes(item.id);
      return `<div class="factor-row" data-factor-row data-factor-id="${escapeHtml(item.id)}" data-factor-asset="${escapeHtml(item.asset)}" data-factor-field="${escapeHtml(item.field)}" data-factor-frequency="${escapeHtml(item.frequency)}" data-factor-unit="${escapeHtml(item.unit)}">
        <div>
          <strong>${escapeHtml(factorDisplayName(item))}</strong>
          <span>${escapeHtml(factorScopeBadge(item))}</span>
          ${renderSemanticMeta(item, " data-variable-card-semantic")}
        </div>
        <div class="factor-actions">
          <button class="btn" data-set-y="${escapeHtml(item.id)}"${canSetY && item.id !== selectedY ? "" : " disabled"} title="${escapeHtml(item.id === selectedY ? currentYLabel() : (canSetY ? ui.setY : ui.yUnsupported))}">${escapeHtml(item.id === selectedY ? currentYLabel() : ui.setY)}</button>
          <button class="btn" data-add-x="${escapeHtml(item.id)}"${isX ? " disabled" : ""}>${escapeHtml(addXLabel())}</button>
        </div>
      </div>`;
    }).join("") || `<div class="empty">${escapeHtml(ui.noFactors)}</div>`}
    <p class="note">${escapeHtml(semantic.rawLink)}</p>
  </div>`;
}

function renderYBasket() {
  const ui = local();
  const item = yFactor();
  if (!item) return `<div class="result-blocker">${escapeHtml(tx("workbench").selectYFirst || "Select Y first")}</div>`;
  return `<div class="selected-variable y-variable" data-selected-y data-selected-y-id="${escapeHtml(item.id)}">
    <strong>${escapeHtml(factorDisplayName(item))}</strong>
    ${renderSemanticMeta(item, " data-y-semantic-metadata")}
  </div>`;
}

function renderXBasket() {
  const ui = local();
  const groups = new Map();
  for (const item of xFactors()) {
    if (!groups.has(item.asset)) groups.set(item.asset, []);
    groups.get(item.asset).push(item);
  }
  if (!selectedX.length) return `<div class="empty">${escapeHtml(ui.noX)}</div>`;
  return `<div class="x-variable-groups" data-selected-x data-selected-x-count="${escapeHtml(selectedX.length)}">${[...groups.entries()].map(([asset, items]) => `<section class="x-group"><h4>${escapeHtml(label(asset, "asset"))} <span class="x-group-count">${escapeHtml(items.length)}</span></h4>${items.map((item) => {
    const index = selectedX.indexOf(item.id);
    return `<div class="selected-variable" data-selected-x-id="${escapeHtml(item.id)}">
      <div><strong>${escapeHtml(factorDisplayName(item))}</strong>${renderSemanticMeta(item, " data-x-semantic-metadata")}</div>
      <div class="factor-actions">
        <button class="btn" data-move-x="${escapeHtml(item.id)}" data-direction="up"${index === 0 ? " disabled" : ""}>${escapeHtml(ui.moveUp)}</button>
        <button class="btn" data-move-x="${escapeHtml(item.id)}" data-direction="down"${index === selectedX.length - 1 ? " disabled" : ""}>${escapeHtml(ui.moveDown)}</button>
        <button class="btn" data-remove-x="${escapeHtml(item.id)}">${escapeHtml(ui.remove)}</button>
      </div>
    </div>`;
  }).join("")}</section>`).join("")}</div>`;
}

function visibleAssetRows() {
  const base = yFactor()?.asset || "a_share";
  const rows = assetRows.filter((row) => (base === "etf" ? row.market === "etf" : row.market === "a_share"));
  return showSelectedAssetsOnly ? rows.filter((row) => selectedAssets.has(row.code)) : rows;
}

function renderAdvancedSampleFilter() {
  const labels = tx("workbench");
  const ui = local();
  const y = yFactor();
  const rows = visibleAssetRows().map((row) => [
    escapeHtml(row.code),
    escapeHtml(labels.nameMissing || "Name field not connected"),
    escapeHtml(label(row.market, "asset")),
    escapeHtml(labels.industryMissing || "Industry field not connected"),
    escapeHtml(selectedAssets.has(row.code) ? (labels.included || "Included") : (labels.excluded || "Excluded")),
  ]);
  return `<details class="advanced-sample-filter" data-advanced-sample-filter${advancedOpen ? " open" : ""}>
    <summary>${escapeHtml(labels.advancedSampleFilter || "Advanced Sample Filter")}</summary>
    <div class="sample-filter-body">
      <div class="catalog-fields">
        <span><b>${escapeHtml(ui.samplePreset)}</b>${escapeHtml(defaultSamplePreset())}</span>
        <span><b>${escapeHtml(labels.baseAssetCategory || "Base asset")}</b>${escapeHtml(label(y?.asset || "a_share", "asset"))}</span>
        <span><b>${escapeHtml(ui.manualSupported)}</b>${escapeHtml(ui.notSupported)}</span>
        <span><b>${escapeHtml(ui.sampleConnected)}</b>${escapeHtml(ui.sampleBlocker)}</span>
      </div>
      <div class="tag-list sample-presets">
        ${samplePresetOptions().map((preset) => `<button class="tag" data-sample-preset="${escapeHtml(preset)}">${escapeHtml(preset)}</button>`).join("")}
      </div>
      <div class="actions">
        <input class="input" id="mw-sample-search" placeholder="${escapeHtml(labels.assetSearch || "Search code / name")}">
        <button class="btn" data-sample-select-visible>${escapeHtml(labels.selectVisible || "Select all")}</button>
        <button class="btn" data-sample-clear-visible>${escapeHtml(labels.clearVisible || "Clear all")}</button>
        <button class="btn" data-sample-show-selected>${escapeHtml(ui.selectedOnly)}</button>
      </div>
      ${table([labels.code || "Code", labels.name || "Name", labels.market || "Market", labels.industry || "Industry", labels.include || "Include"], rows)}
    </div>
  </details>`;
}

function renderVariableSelection() {
  const labels = tx("workbench");
  const ui = local();
  const semantic = semanticLabels();
  return `<article class="card variable-card">
    <h3>2. ${escapeHtml(semantic.library)}</h3>
    <div class="variable-selection-grid">
      <section class="factor-database-column">
        <div class="factor-pane-header"><h4>${escapeHtml(semantic.library)}</h4>${renderFactorFilters()}</div>
        ${renderFactorLibrary()}
      </section>
      <section class="variable-basket-column">
        <div class="basket-pane-header"><h4>${escapeHtml(labels.variableBasket || "Variable Basket")}</h4></div>
        <section class="basket-fixed-y"><h5>${escapeHtml(ui.y)}</h5>${renderYBasket()}</section>
        <section class="x-basket-panel"><h5>${escapeHtml(ui.x)} <span class="x-total-count">${escapeHtml(ui.count)}=${escapeHtml(selectedX.length)}</span></h5><div class="x-basket-scroll">${renderXBasket()}</div></section>
        ${renderAdvancedSampleFilter()}
      </section>
    </div>
  </article>`;
}

function renderTimeRange() {
  const labels = tx("workbench");
  return `<article class="card"><h3>3. ${escapeHtml(labels.timeRange || "Time Range")}</h3>
    <div class="mw-date-grid">
      <label>${escapeHtml(labels.start || "Start Date")}<input class="input" type="date" id="mw-start" value="${escapeHtml(workbenchControls.date_start)}"></label>
      <label>${escapeHtml(labels.end || "End Date")}<input class="input" type="date" id="mw-end" value="${escapeHtml(workbenchControls.date_end)}"></label>
    </div>
    <label>${escapeHtml(labels.frequency || "Frequency")}<select class="input" id="mw-frequency">
      <option value="daily"${workbenchControls.frequency === "daily" ? " selected" : ""}>${escapeHtml(labels.daily || "Daily")}</option>
      <option value="weekly"${workbenchControls.frequency === "weekly" ? " selected" : ""}>${escapeHtml(labels.weekly || "Weekly")}</option>
      <option value="monthly"${workbenchControls.frequency === "monthly" ? " selected" : ""}>${escapeHtml(labels.monthly || "Monthly")}</option>
    </select></label>
  </article>`;
}

function renderModelSettings() {
  const labels = tx("workbench");
  const ui = local();
  const showRolling = rollingEnabled || modelType === "rolling_ols";
  const options = workbenchModels().map((model) => {
    const text = model.enabled ? modelLabel(model) : `${modelLabel(model)} - ${modelReason(model)}`;
    return `<option value="${escapeHtml(model.id)}"${modelType === model.id ? " selected" : ""}${model.enabled ? "" : " disabled"}>${escapeHtml(text)}</option>`;
  }).join("");
  return `<article class="card"><h3>4. ${escapeHtml(labels.modelSettings || "Model Settings")}</h3>
    <label>${escapeHtml(labels.modelType || "Model Type")}<select class="input" id="mw-model-type">
      ${options}
    </select></label>
    <label>${escapeHtml(ui.standardization)}<select class="input" id="mw-standardization"><option value="z_score"${workbenchControls.standardization === "z_score" ? " selected" : ""}>${lang() === "en" ? "z-score" : "z-score 标准化"}</option><option value="none"${workbenchControls.standardization === "none" ? " selected" : ""}>${lang() === "en" ? "None" : "不标准化"}</option></select></label>
    <label>${escapeHtml(ui.missingPolicy)}<select class="input" id="mw-missing"><option value="inner_join_aligned_dates"${workbenchControls.missing_policy === "inner_join_aligned_dates" ? " selected" : ""}>${lang() === "en" ? "Inner join aligned dates" : "共同日期内连接"}</option><option value="drop_missing_rows"${workbenchControls.missing_policy === "drop_missing_rows" ? " selected" : ""}>${lang() === "en" ? "Drop missing rows" : "删除缺失行"}</option></select></label>
    <label class="checkbox-label"><input type="checkbox" id="mw-enable-rolling"${showRolling ? " checked" : ""}> ${escapeHtml(ui.rollingEnabled)}</label>
    <div class="rolling-options${showRolling ? "" : " is-hidden"}" data-rolling-options>
      <label>${escapeHtml(ui.rollingWindow)}<input class="input compact-number" id="mw-rolling-window" type="number" min="5" max="252" value="${escapeHtml(workbenchControls.rolling_window)}"></label>
    </div>
  </article>`;
}

function defaultSamplePreset() {
  const presets = samplePresetOptions();
  if (yFactor()?.asset === "etf" && presets.includes("ETF default pool")) return "ETF default pool";
  return presets[0] || "object_bound_default";
}

function advancedSampleFilterPayload() {
  return {
    enabled: advancedOpen,
    preset: defaultSamplePreset(),
    selected_asset_codes: advancedOpen ? Array.from(selectedAssets) : [],
    show_selected_only: showSelectedAssetsOnly,
    manual_filter_supported: false,
  };
}

function numericControlValue(selector, defaultValue) {
  const value = Number(document.querySelector(selector)?.value);
  return Number.isFinite(value) ? value : defaultValue;
}

function saveWorkbenchControls() {
  workbenchControls = {
    date_start: document.getElementById("mw-start")?.value || workbenchControls.date_start,
    date_end: document.getElementById("mw-end")?.value || workbenchControls.date_end,
    frequency: document.getElementById("mw-frequency")?.value || workbenchControls.frequency,
    rolling_window: numericControlValue("#mw-rolling-window", workbenchControls.rolling_window),
    standardization: document.getElementById("mw-standardization")?.value || workbenchControls.standardization,
    missing_policy: document.getElementById("mw-missing")?.value || workbenchControls.missing_policy,
  };
}

function previewPayload() {
  saveWorkbenchControls();
  const rolling = rollingEnabled || modelType === "rolling_ols";
  return {
    dataset_id: INTERNAL_WORKBENCH_DATASET,
    universe: defaultSamplePreset(),
    date_start: workbenchControls.date_start,
    date_end: workbenchControls.date_end,
    frequency: workbenchControls.frequency,
    target_id: selectedY,
    feature_ids: [...selectedX],
    model_family: modelType,
    rolling_enabled: rolling,
    rolling_window: rolling ? workbenchControls.rolling_window : null,
    standardization: workbenchControls.standardization,
    missing_policy: workbenchControls.missing_policy,
    advanced_sample_filter: advancedSampleFilterPayload(),
    train_mode: "diagnostic_only",
  };
}

async function postWorkbenchJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) throw new Error(`${path} ${response.status}`);
  if (!contentType.includes("application/json")) throw new Error(`${path} returned non-JSON response`);
  return JSON.parse(text);
}

function requestEchoRows(requested, payload) {
  const ui = local();
  const echoed = {
    target_id: payload.target_id || payload.effective_target_id,
    feature_ids: payload.effective_feature_ids || payload.feature_ids,
    date_start: payload.requested_date_start || payload.date_start,
    date_end: payload.requested_date_end || payload.date_end,
    frequency: payload.frequency,
  };
  const missing = [];
  if (echoed.target_id && echoed.target_id !== requested.target_id) missing.push("target_id");
  if (Array.isArray(echoed.feature_ids)) {
    const set = new Set(echoed.feature_ids);
    for (const id of requested.feature_ids) if (!set.has(id)) missing.push(`feature:${id}`);
  }
  if (!payload.effective_feature_ids && !payload.feature_ids) missing.push("feature_ids");
  if (!payload.requested_date_start && !payload.date_start) missing.push("date_start");
  if (!payload.requested_date_end && !payload.date_end) missing.push("date_end");
  if (!payload.frequency) missing.push("frequency");
  const missingText = missing.length ? (lang() === "en" ? "Some requested selections were not echoed" : "部分请求选择未返回") : ui.none;
  return {
    rows: [
    [ui.effectiveY, factorDisplayName(requested.target_id)],
    [ui.xList, requested.feature_ids.map((id) => factorDisplayName(id)).join(", ")],
    [ui.dateRange, dateRangeText(requested.date_start, requested.date_end)],
    [ui.frequency, formatFrequency(requested.frequency, lang())],
    [ui.requestedSample, sampleFilterText(requested.advanced_sample_filter)],
    [ui.ignoredSelection, missingText],
    ],
    technicalHtml: "",
  };
}

function modelObjectScopeRows(payload) {
  const ui = local();
  const scope = payload.model_object_scope || {};
  const target = payload.target_object_identity || scope.target_object_identity || {};
  const features = payload.feature_object_identities || scope.feature_object_identities || [];
  if (!scope.model_object_scope && !target.factor_id && !features.length) return [];
  return [
    [ui.modelObjectScope, localizedScopeValue(scope.model_object_scope || payload.model_object_scope || "")],
    [ui.universeLabel, scope.universe_label || payload.universe_label || ""],
    [ui.panelGrain, localizedScopeValue(scope.panel_grain || payload.panel_grain || "")],
    [ui.joinKeys, (scope.join_keys || payload.join_keys || []).map(localizedScopeValue).join(", ")],
    [ui.entityCount, formatNumber(scope.entity_count ?? payload.entity_count ?? "", 0)],
    [ui.dateCount, formatNumber(scope.date_count ?? payload.date_count ?? "", 0)],
    [ui.sampleRowCount, formatNumber(scope.sample_row_count ?? payload.sample_size_or_valid_rows ?? "", 0)],
    [ui.targetIdentity, localizedIdentityName(target) || factorDisplayName(payload.target_id || "")],
    [ui.featureIdentities, features.map((row) => localizedIdentityName(row)).filter(Boolean).join(", ")],
  ];
}

function sampleFilterText(value) {
  let filter = value;
  if (typeof filter === "string") { try { filter = JSON.parse(filter); } catch { return filter; } }
  if (!filter || typeof filter !== "object") return "";
  const zh = lang() !== "en";
  return [`${zh ? "\u6837\u672c\u8fc7\u6ee4" : "Sample filter"}: ${filter.enabled ? (zh ? "\u5df2\u542f\u7528" : "Enabled") : (zh ? "\u672a\u542f\u7528" : "Disabled")}`, `${zh ? "\u9884\u8bbe\u8d44\u4ea7\u6c60" : "Preset universe"}: ${samplePresetText(filter.preset)}`, `${zh ? "\u5df2\u9009\u8d44\u4ea7" : "Selected assets"}: ${(filter.selected_asset_codes || []).length}`, `${zh ? "\u4ec5\u663e\u793a\u5df2\u9009\u8d44\u4ea7" : "Show selected only"}: ${filter.show_selected_only ? (zh ? "\u662f" : "Yes") : (zh ? "\u5426" : "No")}`, `${zh ? "\u624b\u52a8\u7b5b\u9009" : "Manual filter"}: ${filter.manual_filter_supported ? (zh ? "\u53ef\u7528" : "Available") : (zh ? "\u6682\u4e0d\u53ef\u7528" : "Unavailable")}`].join("; ");
}

function samplePresetText(value) {
  const raw = String(value || "").trim();
  if (raw === "object_bound_default") return lang() === "en" ? "Object-bound default" : "对象绑定默认样本";
  if (raw === "evidence_bound_a_share_panel") return lang() === "en" ? "Evidence-bound A-share panel" : "证据绑定A股面板";
  if (!raw || raw.toLowerCase() === "none") return lang() === "en" ? "None" : local().none;
  return raw;
}

function semanticOptionalText(value) {
  const raw = String(value || "").trim();
  if (!raw || raw.toLowerCase() === "none") return lang() === "en" ? "None" : local().none;
  return raw;
}

function availabilityHtml(payload, requested) {
  const labels = tx("workbench");
  const ui = local();
  const coverage = payload.coverage || {};
  const rows = [
    [ui.status, lang() === "en" ? "Variable definitions checked" : "\u53d8\u91cf\u5b9a\u4e49\u5df2\u6838\u5bf9"],
    [labels.runnable || "Runnable", labels.no || "No"],
    [ui.blockers, semanticLabels().noRun],
    [ui.diagnosticOnly, payload.diagnostic_only === true ? (lang() === "en" ? "Yes" : "是") : (lang() === "en" ? "No" : "否")],
    [ui.productionWrite, payload.production_write === true ? (lang() === "en" ? "Yes" : "是") : (lang() === "en" ? "No" : "否")],
    [labels.validDays || "Valid days", coverage.date_count ?? coverage.valid_trade_days ?? ""],
    [labels.commonDateRange || "Common date range", coverage.date_min && coverage.date_max ? dateRangeText(coverage.date_min, coverage.date_max) : ""],
    ...modelObjectScopeRows(payload),
    ...requestEchoRows(requested, payload).rows,
  ];
  const requestEcho = requestEchoRows(requested, payload);
  return `<section>${table([labels.metric || "Metric", labels.value || "Value"], rows.map((row) => row.map((cell) => escapeHtml(cell))))}${requestEcho.technicalHtml}</section>`;
}

function finalSampleHtml(payload) {
  const labels = tx("workbench");
  const ui = local();
  const finalSample = payload.final_sample || payload.sample_summary;
  if (!finalSample || typeof finalSample !== "object") {
    return `<section data-preview-final-sample><div class="result-blocker" data-final-sample-blocker>${escapeHtml(ui.finalSampleBlocker)}</div></section>`;
  }
  const rows = [
    [labels.dependentY || "Y", factorDisplayName(finalSample.target_id || finalSample.dependent_y || "")],
    [lang() === "en" ? "Selected X" : "已选 X", (finalSample.feature_ids || []).map((id) => factorDisplayName(id)).join(", ")],
    ...modelObjectScopeRows(finalSample),
    [labels.baseAssetCategory || "Base Asset Category", formatAssetCategory(finalSample.base_asset_category || "", lang())],
    [labels.sampleFilter || "Sample Filter", sampleFilterText(finalSample.sample_filter || { preset: finalSample.sample_preset })],
    [labels.assetCount || "Asset Count", formatNumber(finalSample.asset_count ?? "", 0)],
    [labels.commonDateRange || "Common Date Range", finalSample.date_range ? visibleDateRangeText(finalSample.date_range) : (finalSample.common_date_start && finalSample.common_date_end ? dateRangeText(finalSample.common_date_start, finalSample.common_date_end) : "")],
    [labels.validObservationCount || "Valid Observation Count", formatNumber(finalSample.valid_observation_count ?? "", 0)],
    [labels.excludedAssetCount || "Excluded Asset Count", formatNumber(finalSample.excluded_asset_count ?? "", 0)],
    [labels.exclusionReason || "Exclusion Reason", semanticOptionalText(finalSample.exclusion_reason)],
    [lang() === "en" ? "Data source" : "\u6570\u636e\u6765\u6e90", formatSourceName("model_variable_catalog", lang())],
    [lang() === "en" ? "Production write" : "\u751f\u4ea7\u5199\u5165", finalSample.no_production_write === true ? (lang() === "en" ? "No" : "\u5426") : (lang() === "en" ? "Yes" : "\u662f")],
  ];
  return `<section data-preview-final-sample>${table([labels.metric || "Metric", labels.value || "Value"], rows.map((row) => row.map((cell) => escapeHtml(cell))))}</section>`;
}

function previewResultHtml(payload) {
  const labels = tx("workbench");
  const blockers = payload.errors || payload.blockers || payload.data_blockers || [];
  const rows = [
    [labels.runnable || "Runnable", payload.valid === false ? (labels.no || "No") : (labels.previewRunnable || "Variable definitions available")],
    [labels.dataBlockers || "Data limits", blockers.length ? blockers.join("; ") : (labels.noHardBlocker || "No hard stop")],
    [labels.alignmentHint || "Alignment", payload.alignment_status || payload.alignment_hint || ""],
    [labels.previewAction || "Action", labels.noModelExecution || "No model execution in Preview"],
  ];
  return `<section>${table([labels.metric || "Metric", labels.value || "Value"], rows.map((row) => row.map((cell) => escapeHtml(cell))))}</section>`;
}

function renderCoefficientBars(plot) {
  const spec = parseChartSpec(plot);
  const variables = spec.variables || [];
  const values = spec.values || [];
  if (!variables.length || !values.length) return "";
  const maxAbs = Math.max(...values.map((value) => Math.abs(Number(value) || 0)), 1);
  const bars = variables.map((variable, index) => {
    const value = Number(values[index]) || 0;
    const width = Math.max(2, Math.abs(value) / maxAbs * 150);
    return `<div class="mw-chart-bar-row"><span>${escapeHtml(variableDisplayName(variable))}</span><div class="mw-chart-bar-track"><i style="width:${width}px"></i></div><b>${escapeHtml(formatNumber(value, 6))}</b></div>`;
  }).join("");
  return `<div class="mw-chart-panel" data-chart-role="${escapeHtml(plot.plot_role || "")}"><h4>${escapeHtml(plot.title || "")}</h4>${bars}</div>`;
}

function summaryHtmlV22(payload) {
  const ui = local();
  const rows = (payload.summary_statistics || []).map((row) => ({
    variable: variableDisplayName(row.variable || row.field || row.series_id || ""),
    role: row.role === "target" ? "Y" : "X",
    n: formatNumber(row.n ?? row.count ?? row.sample_count ?? "", 0),
    missing: formatRate(row.missing_rate ?? row.missing_pct ?? ""),
    mean: formatNumber(row.mean ?? "", 6),
    median: formatNumber(row.median ?? "", 6),
    std: formatNumber(row.std ?? row.standard_deviation ?? "", 6),
    min: formatNumber(row.min ?? "", 6),
    p25: formatNumber(row.p25 ?? row.q25 ?? "", 6),
    p75: formatNumber(row.p75 ?? row.q75 ?? "", 6),
    max: formatNumber(row.max ?? "", 6),
  }));
  if (!rows.length) return `<div class="result-blocker" data-summary-stats-blocker>${escapeHtml(ui.summaryBlocker)}</div>`;
  const sample = payload.final_sample || payload.sample_summary || {};
  const cards = [
    [lang() === "en" ? "Sample" : "\u6837\u672c", formatNumber(sample.valid_observation_count ?? payload.sample_estimate ?? "", 0)],
    [lang() === "en" ? "Assets" : "\u8d44\u4ea7", formatNumber(sample.asset_count ?? "", 0)],
    [lang() === "en" ? "Dates" : "\u65e5\u671f", sample.date_range ? visibleDateRangeText(sample.date_range) : ""],
    [lang() === "en" ? "Variables" : "\u53d8\u91cf", `${factorDisplayName(payload.target_id || "")} + ${formatNumber((payload.effective_feature_ids || []).length, 0)} X`],
    [lang() === "en" ? "Diagnostic" : "\u8bca\u65ad", lang() === "en" ? "Only" : "\u4ec5\u8bca\u65ad"],
    [lang() === "en" ? "Write" : "\u5199\u5165", lang() === "en" ? "No production write" : "\u4e0d\u5199\u5165\u751f\u4ea7"],
  ];
  const compactRows = rows.map((row) => `<tr><td class="summary-variable-label">${escapeHtml(row.variable)}</td><td>${escapeHtml(row.role)}</td><td data-numeric>${escapeHtml(row.n)}</td><td data-numeric>${escapeHtml(row.missing)}</td><td data-numeric>${escapeHtml(row.mean)}</td><td data-numeric>${escapeHtml(row.median)}</td><td data-numeric>${escapeHtml(row.std)}</td></tr>`).join("");
  const fullRows = rows.map((row) => `<tr><td class="summary-variable-label">${escapeHtml(row.variable)}</td><td>${escapeHtml(row.role)}</td><td data-numeric>${escapeHtml(row.n)}</td><td data-numeric>${escapeHtml(row.missing)}</td><td data-numeric>${escapeHtml(row.mean)}</td><td data-numeric>${escapeHtml(row.median)}</td><td data-numeric>${escapeHtml(row.std)}</td><td data-numeric>${escapeHtml(row.min)}</td><td data-numeric>${escapeHtml(row.p25)}</td><td data-numeric>${escapeHtml(row.p75)}</td><td data-numeric>${escapeHtml(row.max)}</td></tr>`).join("");
  const summaryLabels = {
    variable: lang() === "en" ? "Variable" : "\u53d8\u91cf",
    role: lang() === "en" ? "Role" : "\u89d2\u8272",
    missing: lang() === "en" ? "Missing" : "\u7f3a\u5931\u7387",
    mean: lang() === "en" ? "Mean" : "\u5747\u503c",
    median: lang() === "en" ? "Median" : "\u4e2d\u4f4d\u6570",
    std: lang() === "en" ? "Std" : "\u6807\u51c6\u5dee",
    min: lang() === "en" ? "Min" : "\u6700\u5c0f\u503c",
    max: lang() === "en" ? "Max" : "\u6700\u5927\u503c",
    full: lang() === "en" ? "Full metrics" : "\u5168\u6307\u6807\u8868",
  };
  const note = lang() === "en" ? "Summary statistics are shown only when an analysis service returns them." : "\u4ec5\u5728\u5206\u6790\u670d\u52a1\u8fd4\u56de\u6458\u8981\u7edf\u8ba1\u65f6\u5c55\u793a\u3002";
  return `<section data-summary-readability data-summary-default-view="compact"><div class="summary-card-grid">${cards.map(([name, value]) => `<div class="summary-mini-card"><span>${escapeHtml(name)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div><p class="note">${escapeHtml(note)} ${escapeHtml(ui.realRows)}: ${escapeHtml(rows.length)}</p><div class="summary-table-scroll" data-summary-scroll><table class="table summary-readable-table summary-compact-table" data-summary-readable-table data-summary-compact-table><thead><tr><th>${escapeHtml(summaryLabels.variable)}</th><th>${escapeHtml(summaryLabels.role)}</th><th>N</th><th>${escapeHtml(summaryLabels.missing)}</th><th>${escapeHtml(summaryLabels.mean)}</th><th>${escapeHtml(summaryLabels.median)}</th><th>${escapeHtml(summaryLabels.std)}</th></tr></thead><tbody>${compactRows}</tbody></table></div><details data-summary-full-table><summary>${escapeHtml(summaryLabels.full)}</summary><div class="summary-table-scroll" data-summary-full-scroll><table class="table summary-readable-table summary-full-table"><thead><tr><th>${escapeHtml(summaryLabels.variable)}</th><th>${escapeHtml(summaryLabels.role)}</th><th>N</th><th>${escapeHtml(summaryLabels.missing)}</th><th>${escapeHtml(summaryLabels.mean)}</th><th>${escapeHtml(summaryLabels.median)}</th><th>${escapeHtml(summaryLabels.std)}</th><th>${escapeHtml(summaryLabels.min)}</th><th>P25</th><th>P75</th><th>${escapeHtml(summaryLabels.max)}</th></tr></thead><tbody>${fullRows}</tbody></table></div></details></section>`;
}

function runHtmlV22(payload, requested) {
  const results = payload.results || [];
  const first = results[0] || payload.result || {};
  if (!results.length) return `<section><div class="result-blocker" data-run-result-blocker>${escapeHtml(local().runResultBlocker)}</div></section>`;
  const metric = payload.basic_fit_metrics || {};
  const coeffRows = payload.coefficient_table || first.coefficient_table || [];
  const unavailable = lang() === "en" ? "Not returned by this diagnostic" : "\u5f53\u524d\u8bca\u65ad\u672a\u8fd4\u56de";
  const dateWindow = payload.common_date_start && payload.common_date_end ? dateRangeText(payload.common_date_start, payload.common_date_end) : ((payload.data_window || {}).date_range || "");
  const rows = [
    [lang() === "en" ? "Status" : "\u72b6\u6001", payload.status === "succeeded" ? (lang() === "en" ? "Succeeded" : "\u5df2\u5b8c\u6210") : payload.status],
    [lang() === "en" ? "Model" : "\u6a21\u578b", formatFieldName(first.model_family || requested.model_family || "ols", lang())],
    [lang() === "en" ? "Target" : "\u56e0\u53d8\u91cf", variableDisplayName(payload.effective_target || requested.target_id)],
    [lang() === "en" ? "Selected X" : "\u5df2\u9009 X", (payload.effective_features || payload.effective_feature_ids || requested.feature_ids || []).map((id) => variableDisplayName(id)).join(", ")],
    ...modelObjectScopeRows(payload),
    [lang() === "en" ? "Sample" : "\u6837\u672c", formatNumber(payload.sample_size ?? metric.sample_size ?? first.n_obs ?? "", 0)],
    [lang() === "en" ? "Date window" : "\u65e5\u671f\u7a97\u53e3", dateWindow],
    ["R2", formatNumber(metric.r_squared ?? first.r_squared ?? "", 6)],
    [lang() === "en" ? "Adjusted R2" : "\u8c03\u6574\u62df\u5408\u5ea6", unavailable],
    [lang() === "en" ? "RMSE" : "\u5747\u65b9\u6839\u8bef\u5dee", unavailable],
    [lang() === "en" ? "Selection matched Preview" : "\u4e0e\u9884\u89c8\u9009\u62e9\u4e00\u81f4", payload.selection_fidelity_passed === true ? (lang() === "en" ? "Yes" : "\u662f") : (lang() === "en" ? "No" : "\u5426")],
    [lang() === "en" ? "Write" : "\u5199\u5165", lang() === "en" ? "No production write" : "\u4e0d\u5199\u5165\u751f\u4ea7"],
  ];
  const coeff = coeffRows.length ? table([lang() === "en" ? "Term" : "\u9879", lang() === "en" ? "Variable" : "\u53d8\u91cf", lang() === "en" ? "Coefficient" : "\u7cfb\u6570", lang() === "en" ? "Std. error" : "\u6807\u51c6\u8bef", lang() === "en" ? "t value" : "\u68c0\u9a8c\u7edf\u8ba1\u91cf", lang() === "en" ? "p value" : "\u663e\u8457\u6027\u6982\u7387"], coeffRows.map((row) => [escapeHtml(variableDisplayName(row.term || "")), escapeHtml(variableDisplayName(row.variable || row.term || "")), escapeHtml(formatNumber(row.coefficient, 8)), escapeHtml(row.std_error == null ? unavailable : formatNumber(row.std_error, 6)), escapeHtml(row.t_value == null ? unavailable : formatNumber(row.t_value, 6)), escapeHtml(row.p_value == null ? unavailable : formatNumber(row.p_value, 6))]), " data-coefficient-table") : "";
  const note = lang() === "en" ? "Diagnostic estimates only; not a prediction, trading signal, or investment advice." : "\u4ec5\u8bca\u65ad\u4f30\u8ba1\uff1b\u4e0d\u6784\u6210\u9884\u6d4b\u3001\u4ea4\u6613\u4fe1\u53f7\u6216\u6295\u8d44\u5efa\u8bae\u3002";
  return `<section data-model-results>${table([lang() === "en" ? "Metric" : "\u6307\u6807", lang() === "en" ? "Value" : "\u503c"], rows.map((row) => row.map((cell) => escapeHtml(cell))))}<p class="note">${escapeHtml(note)}</p>${coeff}</section>`;
}

function chartTitleV22(plot) {
  if (plot.plot_role === "coefficient_bar") return lang() === "en" ? "Coefficient sizes" : "\u7cfb\u6570\u5927\u5c0f";
  if (plot.plot_role === "residual_scatter") return lang() === "en" ? "Residual sample" : "\u6b8b\u5dee\u6837\u672c";
  if (plot.plot_role === "fitted_vs_actual") return lang() === "en" ? "Fitted vs actual" : "\u62df\u5408\u4e0e\u5b9e\u9645";
  if (plot.plot_role === "summary_stat_bar") return lang() === "en" ? "Summary statistics" : "\u6458\u8981\u7edf\u8ba1";
  if (plot.plot_role === "correlation_heatmap") return lang() === "en" ? "Correlation matrix" : "\u76f8\u5173\u77e9\u9635";
  if (plot.plot_role === "pca_explained_variance") return lang() === "en" ? "PCA explained variance" : "PCA \u89e3\u91ca\u65b9\u5dee";
  if (plot.plot_role === "pca_loading_bar") return lang() === "en" ? "PC1 loadings" : "PC1 \u8f7d\u8377";
  return lang() === "en" ? "Diagnostic chart" : "\u8bca\u65ad\u56fe\u8868";
}

function renderPointSummaryV22(plot) {
  const spec = parseChartSpec(plot);
  const points = spec.points || [];
  const sample = points.slice(0, 24);
  const svgPoints = sample.map((point, index) => {
    const x = 12 + (index % 12) * 18;
    const y = 20 + Math.min(70, Math.abs(Number(point.residual || point.actual || 0)) % 70);
    return `<circle cx="${x}" cy="${y}" r="3"></circle>`;
  }).join("");
  return `<div class="mw-chart-panel" data-chart-role="${escapeHtml(plot.plot_role || "")}"><h4>${escapeHtml(plot.title || "")}</h4><svg class="mw-mini-scatter" viewBox="0 0 240 110" role="img" aria-label="${escapeHtml(plot.title || "")}">${svgPoints}</svg><p class="note">${escapeHtml(lang() === "en" ? "Rendered points" : "\u5df2\u7ed8\u5236\u70b9")}: ${escapeHtml(formatNumber(spec.point_count || points.length, 0))}</p></div>`;
}

function renderDiagnosticBars(plot) {
  const spec = parseChartSpec(plot);
  const variables = spec.variables || spec.components || [];
  const values = spec.values || [];
  if (!variables.length || !values.length) return renderPointSummaryV22(plot);
  const maxAbs = Math.max(...values.map((value) => Math.abs(Number(value) || 0)), 1);
  const bars = variables.map((variable, index) => {
    const value = Number(values[index]) || 0;
    const width = Math.max(2, Math.abs(value) / maxAbs * 150);
    return `<div class="mw-chart-bar-row"><span>${escapeHtml(variableDisplayName(variable))}</span><div class="mw-chart-bar-track"><i style="width:${width}px"></i></div><b>${escapeHtml(formatNumber(value, 6))}</b></div>`;
  }).join("");
  return `<div class="mw-chart-panel" data-chart-role="${escapeHtml(plot.plot_role || "")}"><h4>${escapeHtml(plot.title || "")}</h4>${bars}<p class="note">${escapeHtml(lang() === "en" ? "Sample" : "\u6837\u672c")}: ${escapeHtml(formatNumber(spec.sample_count ?? "", 0))}</p></div>`;
}

function renderCorrelationMatrix(plot) {
  const spec = parseChartSpec(plot);
  const variables = spec.variables || [];
  const matrix = spec.matrix || [];
  if (!variables.length || !matrix.length) return renderPointSummaryV22(plot);
  const headers = ["", ...variables.map((item) => variableDisplayName(item))];
  const rows = variables.map((variable, rowIndex) => [
    escapeHtml(variableDisplayName(variable)),
    ...variables.map((_column, columnIndex) => escapeHtml(formatNumber(matrix[rowIndex]?.[columnIndex], 4))),
  ]);
  return `<div class="mw-chart-panel" data-chart-role="${escapeHtml(plot.plot_role || "")}"><h4>${escapeHtml(plot.title || "")}</h4>${table(headers, rows)}<p class="note">${escapeHtml(lang() === "en" ? "Sample" : "\u6837\u672c")}: ${escapeHtml(formatNumber(spec.sample_count ?? "", 0))}</p></div>`;
}

function chartHtmlV22(payload) {
  const plots = payload.plots || payload.plot_specs || [];
  if (!plots.length) return `<section><div class="result-blocker">${escapeHtml(local().chartBlocker)}</div></section>`;
  return `<section data-chart-results>${plots.map((plot) => {
    const safePlot = { ...plot, title: chartTitleV22(plot) };
    if (safePlot.plot_role === "coefficient_bar") return renderCoefficientBars(safePlot);
    if (safePlot.plot_role === "correlation_heatmap") return renderCorrelationMatrix(safePlot);
    if (["summary_stat_bar", "pca_explained_variance", "pca_loading_bar"].includes(safePlot.plot_role)) return renderDiagnosticBars(safePlot);
    return renderPointSummaryV22(safePlot);
  }).join("")}<p class="note">${escapeHtml(lang() === "en" ? "Charts render diagnostic output from the completed run only." : "\u56fe\u8868\u4ec5\u6e32\u67d3\u672c\u6b21\u5df2\u5b8c\u6210\u8bca\u65ad\u7684\u8f93\u51fa\u3002")}</p></section>`;
}

function historyHtmlV22(payload) {
  const rows = Array.isArray(payload.history_rows) && payload.history_rows.length ? payload.history_rows : (payload.history ? [payload.history] : []);
  if (!rows.length) return `<section><div class="result-blocker" data-history-blocker>${escapeHtml(local().historyBlocker)}</div></section>`;
  const headers = lang() === "en" ? ["Time", "Model", "Target", "X count", "Sample", "Date range", "Status", "Charts", "Action"] : ["\u65f6\u95f4", "\u6a21\u578b", "\u76ee\u6807", "X \u6570", "\u6837\u672c", "\u65e5\u671f\u8303\u56f4", "\u72b6\u6001", "\u56fe\u8868", "\u64cd\u4f5c"];
  const body = rows.slice(0, 10).map((history) => [
    escapeHtml(String(history.created_at || "").replace("T", " ").slice(0, 19)),
    escapeHtml(formatFieldName(history.model_family || "ols", lang())),
    escapeHtml(variableDisplayName(history.target_id || payload.effective_target || "")),
    escapeHtml(formatNumber(history.feature_count ?? (payload.effective_features || []).length, 0)),
    escapeHtml(formatNumber(history.sample_size ?? payload.sample_size ?? "", 0)),
    escapeHtml(history.date_range || (history.common_date_start && history.common_date_end ? dateRangeText(history.common_date_start, history.common_date_end) : "")),
    escapeHtml(history.status === "succeeded" ? (lang() === "en" ? "Succeeded" : "\u5df2\u5b8c\u6210") : (history.status || "")),
    escapeHtml(formatNumber(history.plot_count ?? "", 0)),
    escapeHtml(`${lang() === "en" ? "View" : "\u67e5\u770b"} ${history.run_label || `#${String(history.run_id || payload.run_id || "").slice(-6)}`}`),
  ]);
  return `<section data-history-results>${table(headers, body)}</section>`;
}

function renderOptionsBlocker() {
  const labels = tx("workbench");
  const message = backendOptionsError
    ? (lang() === "en"
      ? "The model-variable catalog is temporarily unavailable. Check the backend service and try again; raw fields will not be substituted."
      : "\u6a21\u578b\u53d8\u91cf\u76ee\u5f55\u6682\u65f6\u4e0d\u53ef\u7528\u3002\u8bf7\u68c0\u67e5\u540e\u7aef\u670d\u52a1\u540e\u91cd\u8bd5\uff1b\u9875\u9762\u4e0d\u4f1a\u7528\u539f\u59cb\u5b57\u6bb5\u66ff\u4ee3\u6a21\u578b\u53d8\u91cf\u3002")
    : (lang() === "en" ? "Loading the model-variable catalog." : "\u6b63\u5728\u52a0\u8f7d\u6a21\u578b\u53d8\u91cf\u76ee\u5f55\u3002");
  document.getElementById("workspace-main").innerHTML = `<div class="page modeling-workbench">
    ${head(labels.kicker, labels.title, labels.subtitle)}
    <section class="card">
      <div class="result-blocker" data-backend-options-blocker data-backend-unavailable-guidance="${backendOptionsError ? "true" : "false"}">${escapeHtml(message)}</div>
      ${backendOptionsError ? `<div class="actions"><button class="btn" id="mw-retry-options">${escapeHtml(lang() === "en" ? "Retry" : "\u91cd\u8bd5")}</button></div>` : ""}
    </section>
  </div>`;
  document.getElementById("mw-retry-options")?.addEventListener("click", () => {
    backendOptionsError = "";
    loadBackendOptions();
  });
}

function renderWorkbench() {
  const labels = tx("workbench");
  document.getElementById("workspace-main").innerHTML = `<div class="page modeling-workbench">
    ${head(labels.kicker, labels.title, labels.subtitle)}
    <div class="workbench-layout workbench-layout-single">
      <section class="workbench-config workbench-v4-config">
        <article class="card"><h3>1. ${escapeHtml(labels.researchQuestion || "Research Question")}</h3>
          <label>${escapeHtml(labels.studyName || "Study Name")}<input class="input" id="mw-study-name" value="${escapeHtml(labels.defaultQuestion || "Diagnostic relationship study")}"></label>
          <label>${escapeHtml(labels.question || "Research Question")}<textarea class="input" id="mw-question">${escapeHtml(labels.defaultQuestion || "")}</textarea></label>
        </article>
        ${renderVariableSelection()}
        ${renderTimeRange()}
        ${renderModelSettings()}
        <article class="card"><h3>5. ${escapeHtml(labels.previewRun || "Variable Check")}</h3>
          <p>${escapeHtml(labels.previewExplanation || "")}</p>
          <div class="actions"><button class="btn" id="mw-preview"${previewInFlight ? " disabled" : ""}>${escapeHtml(labels.preview || "Check Variables")}</button></div>
          <p class="note">${escapeHtml(semanticLabels().noRun)}</p>
        </article>
      </section>
    </div>
  </div>`;
}

function bindFactorInteractions() {
  document.querySelector("[data-factor-asset-filter]")?.addEventListener("change", (event) => { saveWorkbenchControls(); filters.asset = event.target.value; renderModelingWorkbench(); });
  document.querySelector("[data-factor-field-filter]")?.addEventListener("change", (event) => { saveWorkbenchControls(); filters.field = event.target.value; renderModelingWorkbench(); });
  document.querySelector("[data-factor-unit-filter]")?.addEventListener("change", (event) => { saveWorkbenchControls(); filters.unit = event.target.value; renderModelingWorkbench(); });
  document.querySelector("[data-factor-frequency-filter]")?.addEventListener("change", (event) => { saveWorkbenchControls(); filters.frequency = event.target.value; renderModelingWorkbench(); });
  document.getElementById("mw-factor-search")?.addEventListener("input", (event) => { saveWorkbenchControls(); filters.search = event.target.value; renderModelingWorkbench(); });
  document.querySelectorAll("[data-set-y]").forEach((button) => button.addEventListener("click", () => { saveWorkbenchControls(); selectedY = button.dataset.setY; renderModelingWorkbench(); }));
  document.querySelectorAll("[data-add-x]").forEach((button) => button.addEventListener("click", () => { saveWorkbenchControls(); if (!selectedX.includes(button.dataset.addX)) selectedX.push(button.dataset.addX); renderModelingWorkbench(); }));
  document.querySelectorAll("[data-remove-x]").forEach((button) => button.addEventListener("click", () => { saveWorkbenchControls(); selectedX = selectedX.filter((id) => id !== button.dataset.removeX); renderModelingWorkbench(); }));
  document.querySelectorAll("[data-move-x]").forEach((button) => button.addEventListener("click", () => {
    saveWorkbenchControls();
    const id = button.dataset.moveX;
    const index = selectedX.indexOf(id);
    const next = button.dataset.direction === "up" ? index - 1 : index + 1;
    if (index >= 0 && next >= 0 && next < selectedX.length) {
      [selectedX[index], selectedX[next]] = [selectedX[next], selectedX[index]];
      renderModelingWorkbench();
    }
  }));
  document.querySelector("[data-advanced-sample-filter]")?.addEventListener("toggle", (event) => { saveWorkbenchControls(); advancedOpen = event.target.open; });
  document.querySelector("[data-sample-show-selected]")?.addEventListener("click", () => { saveWorkbenchControls(); showSelectedAssetsOnly = !showSelectedAssetsOnly; renderModelingWorkbench(); });
  document.querySelector("[data-sample-select-visible]")?.addEventListener("click", () => { saveWorkbenchControls(); visibleAssetRows().forEach((row) => selectedAssets.add(row.code)); renderModelingWorkbench(); });
  document.querySelector("[data-sample-clear-visible]")?.addEventListener("click", () => { saveWorkbenchControls(); visibleAssetRows().forEach((row) => selectedAssets.delete(row.code)); renderModelingWorkbench(); });
  document.querySelectorAll("#mw-start, #mw-end, #mw-frequency, #mw-standardization, #mw-missing, #mw-rolling-window").forEach((input) => input.addEventListener("change", saveWorkbenchControls));
  document.getElementById("mw-model-type")?.addEventListener("change", (event) => { saveWorkbenchControls(); modelType = event.target.value; rollingEnabled = modelType === "rolling_ols" || rollingEnabled; renderModelingWorkbench(); });
  document.getElementById("mw-enable-rolling")?.addEventListener("change", (event) => { saveWorkbenchControls(); rollingEnabled = event.target.checked; renderModelingWorkbench(); });
}

function bindPreviewAction() {
  document.getElementById("mw-preview")?.addEventListener("click", async () => {
    if (previewInFlight) return;
    const payload = previewPayload();
    previewInFlight = true;
    const previewButton = document.getElementById("mw-preview");
    if (previewButton) previewButton.disabled = true;
    const ui = local();
    const handle = startOperationPanel({
      mode: "workbench",
      titleText: ui.previewStatus,
      statusKey: "running",
      activeStep: "validate",
      steps: ["validate", "coverage", "summary", "final_sample"],
      targetText: `${ui.previewTarget}: ${variableDisplayName(payload.target_id)}`,
      progressText: `${ui.dateRange}: ${dateRangeText(payload.date_start, payload.date_end)}`,
    });
    try {
      const result = await postWorkbenchJson("/api/modeling-workbench/preview", payload);
      finishOperationPanel(handle, {
        statusKey: "completed",
        resultText: result.valid === false ? ui.exactBlocker : ui.realRows,
        activeTab: tx("workbench").tabs[0],
        resultHtmlByTab: {
          [tx("workbench").tabs[0]]: availabilityHtml(result, payload),
          [tx("workbench").tabs[1]]: summaryHtmlV22(result),
          [tx("workbench").tabs[2]]: finalSampleHtml(result),
          [tx("workbench").tabs[3]]: previewResultHtml(result),
        },
      });
    } catch (error) {
      const message = lang() === "en"
        ? "The variable check could not reach the backend. Check the service and try again."
        : "\u53d8\u91cf\u68c0\u67e5\u6682\u65f6\u65e0\u6cd5\u8fde\u63a5\u540e\u7aef\u3002\u8bf7\u68c0\u67e5\u670d\u52a1\u540e\u91cd\u8bd5\u3002";
      failOperationPanel(handle, { status: tx("workbench").previewError || "Preview failed", errorHtml: `<div class="result-blocker">${escapeHtml(message)}</div>` });
    } finally {
      previewInFlight = false;
      if (previewButton) previewButton.disabled = false;
    }
  });
}

export function renderModelingWorkbench() {
  setWorkbenchBridge();
  if (!backendOptions) {
    renderOptionsBlocker();
    if (!backendOptionsError) loadBackendOptions();
    return;
  }
  applyBackendOptionDefaults();
  renderWorkbench();
  bindFactorInteractions();
  bindPreviewAction();
}
