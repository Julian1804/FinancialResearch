export class ApiError extends Error {
  constructor(url, response, detail, requestId, operationId, errorClass) {
    const code = detail?.code || detail?.error_type || detail?.reason || "request_failed";
    const message = detail?.message || detail?.error || code;
    super(message);
    this.name = "ApiError";
    this.url = url;
    this.status = response.status;
    this.code = String(code);
    this.detail = detail || {};
    this.requestId = requestId || "";
    this.operationId = operationId || detail?.operation_id || "";
    this.errorClass = errorClass || detail?.error_class || "";
  }
}

const ZH_ERROR_CODE_MESSAGES = {
  invalid_date_range: "日期范围无效；请确认开始日期不晚于结束日期，并符合页面允许的区间。",
  listing_not_found: "在所选日期未找到对应的上市期。",
  result_too_large: "返回结果超过行数上限；请缩短日期范围或调整允许的行数。",
  unsupported_metric: "当前产品不支持所选指标。",
  unsupported_adjustment_basis: "当前版本不支持所选复权口径。",
  series_unavailable: "所选对象和指标当前没有可用时间序列。",
  invalid_alias: "交易所或证券代码不在当前中国 A 股查询范围内。",
  invalid_row_limit: "返回行数超出允许范围。",
  request_validation_failed: "请求参数无效，请检查输入后重试。",
  subject_not_found: "未找到对应的基金对象。",
  empty_search: "请输入基金名称或代码。",
  invalid_subject_type: "当前产品不支持该对象类型。",
  snapshot_binding_conflict: "请求所用版本与当前固定版本不一致，请重新打开页面。",
  release_binding_unavailable: "固定的服务版本当前不可用，请重新打开页面。",
  active_release_unavailable: "当前服务版本不可用，请稍后重试。",
  release_unavailable: "当前服务版本不可用，请稍后重试。",
  fund_component_unavailable: "当前基金查询服务不可用，请稍后重试。",
  fund_snapshot_unavailable: "当前基金数据版本不可用，请稍后重试。",
  china_equity_component_unavailable: "当前中国股票查询服务不可用，请稍后重试。",
  china_equity_metadata_unavailable: "当前中国股票服务元数据不可用，请稍后重试。",
  invalid_research_date_range: "研究日期范围无效，请检查开始和结束日期。",
  invalid_series_selection: "请选择当前分析方法要求的数据项。",
  duplicate_series_selection: "同一项数据不能重复选择。",
  unsupported_alignment_policy: "当前研究只支持按共同观测日期交集对齐。",
  research_policy_series_limit: "所选数据项数量超出当前分析方法的范围。",
  research_policy_interval_limit: "分析日期范围超出当前方法允许的跨度。",
  unsupported_research_series: "所选对象或指标不在当前分析方法的支持范围内。",
  invalid_adjustment_basis: "基金数据不接受股票价格复权口径。",
  research_release_unavailable: "当前统计分析服务不可用，请稍后重试。",
  series_identity_unavailable: "分析结果无法确认所选数据的身份；请勿使用此结果。",
  research_release_binding_mismatch: "分析所用数据版本与本次运行不一致；请重新运行。",
};

const EN_ERROR_CODE_MESSAGES = {
  invalid_date_range: "Check the start and end dates for this query.",
  invalid_research_date_range: "Check the analysis start and end dates.",
  invalid_search: "Enter a valid name, code or alias.",
  empty_search: "Enter a fund name or code.",
  result_too_large: "The result exceeds the row limit. Shorten the date range or lower the requested rows.",
  research_policy_interval_limit: "The analysis period is longer than this method allows.",
  research_policy_series_limit: "The number of inputs is outside this method's supported range.",
  invalid_series_selection: "Select the inputs required by this analysis method.",
  duplicate_series_selection: "The same data input cannot be selected twice.",
  series_unavailable: "This object has no available data for the selected measure.",
  subject_not_found: "This fund object could not be found.",
  listing_not_found: "This listing could not be found for the selected identity and date.",
  release_binding_unavailable: "The data version used by this view is no longer available. Reopen the page.",
  snapshot_binding_conflict: "The data version used by this view has changed. Reopen the page.",
  active_release_unavailable: "The current data service is unavailable. Try again later.",
  release_unavailable: "The current data service is unavailable. Try again later.",
  fund_component_unavailable: "Fund data is unavailable right now. Try again later.",
  china_equity_component_unavailable: "Equity data is unavailable right now. Try again later.",
  research_release_unavailable: "Statistical analysis is unavailable right now. Try again later.",
  unsupported_research_series: "This object or measure is not supported by the selected analysis method.",
  unsupported_adjustment_basis: "Only unadjusted Equity close prices are supported here.",
  series_identity_unavailable: "The analysis result could not confirm the selected data identity. Do not use this result.",
  research_release_binding_mismatch: "The result does not match the data version used for this run. Run the analysis again.",
  no_common_observations: "The selected inputs have no shared observation dates in this period.",
  zero_change_denominator: "A percentage change cannot be calculated because a previous observed value is zero.",
};

const EN_ERROR_CLASS_MESSAGES = {
  request_invalid: "Check the entered values and try again.",
  semantic_unsupported: "This request is outside the currently supported data or analysis range.",
  identity_unresolved_or_ambiguous: "The financial object could not be identified uniquely. Check the name, code and market.",
  data_unavailable: "The requested data is unavailable.",
  serving_state_invalid: "The data service changed or is unavailable. Reopen the page and try again.",
  conflict_or_busy: "Another operation is in progress. Try again shortly.",
  provider_or_update_failed: "The data update did not complete. Existing published data may still be usable.",
  internal_failure: "The service could not complete the request. Try again later or contact support.",
};

const ZH_ERROR_CLASS_MESSAGES = {
  request_invalid: "请求参数无效，请检查输入后重试。",
  semantic_unsupported: "当前请求超出此产品已支持的范围。",
  identity_unresolved_or_ambiguous: "无法唯一确定所请求的金融对象，请检查标识与日期。",
  data_unavailable: "请求的数据当前不可用。",
  provider_or_update_failed: "数据更新未完成，请记录诊断标识并稍后重试。",
  serving_state_invalid: "当前服务状态不可用或已发生变化，请刷新后重试。",
  conflict_or_busy: "当前请求与正在进行的操作冲突，请稍后重试。",
  internal_failure: "服务处理失败，请记录诊断标识并稍后重试。",
};

function localizedApiMessage(error, language) {
  if (language === "en") return EN_ERROR_CODE_MESSAGES[error.code]
    || EN_ERROR_CLASS_MESSAGES[error.errorClass]
    || "The request could not be completed. Open technical details if support needs the error code.";
  return ZH_ERROR_CODE_MESSAGES[error.code]
    || ZH_ERROR_CLASS_MESSAGES[error.errorClass]
    || "请求未完成；此错误暂无可安全本地化的结构化说明。";
}

function responseContext(response) {
  return {
    requestId: response.headers.get("X-FR-Request-ID") || "",
    operationId: response.headers.get("X-FR-Operation-ID") || "",
    errorClass: response.headers.get("X-FR-Error-Class") || "",
  };
}

export async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  const contentType = response.headers.get("content-type") || "";
  let payload = null;
  if (contentType.includes("application/json") && text) {
    try { payload = JSON.parse(text); }
    catch (error) { throw new Error(`${url} returned invalid JSON`); }
  }
  const context = responseContext(response);
  if (!response.ok) {
    const detail = payload?.detail && typeof payload.detail === "object" ? payload.detail : (payload || {});
    throw new ApiError(url, response, detail, context.requestId, context.operationId, context.errorClass);
  }
  if (!contentType.includes("application/json") || payload === null) {
    throw new Error(`${url} returned a non-JSON response`);
  }
  return payload;
}

function postJson(url, payload = {}) {
  return requestJson(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

function query(values) {
  const result = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (Array.isArray(value)) value.forEach((item) => result.append(key, item));
    else if (value !== undefined && value !== null && value !== "") result.set(key, value);
  });
  return result.toString();
}

function fundParams(binding, values = {}) {
  return query({
    access_mode: binding.access_mode,
    snapshot_id: binding.snapshot_id,
    manifest_sha256: binding.manifest_sha256,
    release_id: binding.release_id,
    release_hash: binding.release_hash,
    ...values,
  });
}

function equityParams(binding, values = {}) {
  return query({release_id: binding.release_id, release_hash: binding.release_hash, ...values});
}

export function formatApiError(error, language = "zh", diagnostics = false) {
  if (!(error instanceof ApiError)) {
    if (diagnostics) return String(error?.message || error || "Unknown error");
    return language === "en" ? "The request could not be completed. Try again or contact support." : "请求未完成，请重试或联系维护人员。";
  }
  const parts = [localizedApiMessage(error, language)];
  if (!diagnostics) return parts[0];
  if (error.code && error.code !== error.message) parts.push(`${language === "en" ? "Code" : "代码"}: ${error.code}`);
  if (error.operationId) parts.push(`${language === "en" ? "Operation" : "操作"}: ${error.operationId}`);
  if (error.requestId) parts.push(`${language === "en" ? "Request" : "请求"}: ${error.requestId}`);
  return parts.join(" · ");
}

export const workspaceApi = {
  system: {
    health: () => requestJson("/api/health"),
    readiness: () => requestJson("/api/readiness"),
    capabilities: () => requestJson("/api/capabilities"),
    configuration: () => requestJson("/api/data-console/data-configuration"),
    update: () => postJson("/api/data-console/update"),
    lifecycle: (values = {}) => requestJson(`/api/data-console/operation-lifecycle?${query({
      scope: values.scope,
      limit: values.limit || 20,
      snapshot_id: values.snapshot_id,
      release_id: values.release_id,
    })}`),
  },
  funds: {
    releases: () => requestJson("/api/funds/releases"),
    session: (payload) => postJson("/api/funds/session", payload),
    update: () => postJson("/api/funds/update"),
    search: (binding, q, aliasEffectiveDate = "") => requestJson(`/api/funds/search?${fundParams(binding, {q, alias_effective_date: aliasEffectiveDate})}`),
    subject: (binding, subjectType, subjectId) => requestJson(`/api/funds/subject?${fundParams(binding, {subject_type: subjectType, subject_id: subjectId})}`),
    timeseries: (binding, request) => requestJson(`/api/funds/timeseries?${fundParams(binding, request)}`),
    nonpromoted: (binding, externalCode = "") => requestJson(`/api/funds/nonpromoted-summary?${fundParams(binding, {external_code: externalCode})}`),
  },
  equity: {
    session: () => requestJson("/api/equity/china/session"),
    search: (binding, q, limit = 20) => requestJson(`/api/equity/china/search?${equityParams(binding, {q, limit})}`),
    resolve: (binding, request) => requestJson(`/api/equity/china/resolve?${equityParams(binding, request)}`),
    timeseries: (binding, request) => requestJson(`/api/equity/china/timeseries?${equityParams(binding, request)}`),
    update: () => postJson("/api/data-console/equity/china/update"),
  },
  research: {
    comparativeSeriesPolicy: () => requestJson("/api/research/comparative-series/policy"),
    comparativeSeriesRun: (payload) => postJson("/api/research/comparative-series/run", payload),
  },
  modeling: {
    models: () => requestJson("/api/research/modeling/models"),
    preview: (payload) => postJson("/api/research/modeling/preview", payload),
    run: (payload) => postJson("/api/research/modeling/run", payload),
    compare: (payload) => postJson("/api/research/modeling/compare", payload),
    optimize: (payload) => postJson("/api/research/modeling/optimize", payload),
    runs: (limit = 20) => requestJson(`/api/research/modeling/runs?${query({limit})}`),
    detail: (runId) => requestJson(`/api/research/modeling/runs/${encodeURIComponent(runId)}`),
    cancel: (runId) => postJson(`/api/research/modeling/runs/${encodeURIComponent(runId)}/cancel`),
    restart: (runId) => postJson(`/api/research/modeling/runs/${encodeURIComponent(runId)}/restart`),
    exportUrl: (runId) => `/api/research/modeling/runs/${encodeURIComponent(runId)}/export`,
  },
};
