import {workspaceApi} from "./api.js";
import {escapeHtml} from "./components.js";
import {setLifecycleState, state} from "./state.js";

export const LIFECYCLE_SCOPES = {
  Fund: {componentId: "CN_PUBLIC_FUND", labelKey: "fund", operationType: "fund_update"},
  Equity: {componentId: "CN_A_SHARE", labelKey: "equity", operationType: "china_equity_update"},
};

export const UPDATE_SCOPES = {
  "fund.china.public": {componentId: "CN_PUBLIC_FUND", labelKey: "fundScope", universe: "Fund"},
  "equity.china.mainland": {componentId: "CN_A_SHARE", labelKey: "mainlandScope", universe: "Equity"},
  "equity.china.hong_kong": {componentId: "CN_A_SHARE", labelKey: "hongKongScope", universe: "Equity"},
};

const COPY = {
  zh: {
    status: "数据更新", platformReady: "数据服务已连接", platformUnavailable: "数据服务暂不可用",
    noUniverse: "当前配置未启用任何数据范围", configured: "已启用", disabled: "未启用",
    unconfigured: "尚未配置数据", unconfiguredReason: "请先建立当前数据配置。",
    authorityUnset: "当前有效配置未确立", authorityUnsetReason: "存在历史配置资料，但当前有效配置尚未确立；需要处理配置。",
    configurationUnavailable: "配置状态未知", lifecycleUnavailable: "暂时无法确认数据生命周期状态。",
    ready: "有可用数据", absent: "尚无可用数据", initializing: "正在首次载入", updating: "正在更新",
    recovering: "正在恢复中断的更新", updated: "上次更新已完成", noChange: "上次更新未发现变化",
    busy: "另一个更新正在进行", failed: "更新失败，但现有数据仍可用", failedNoData: "初始化未完成，当前没有可用数据",
    blocked: "需要配置或处理后才能更新", unresolved: "中断状态尚未确认", unavailable: "当前数据不可服务",
    refresh: "刷新以使用当前数据", newer: "有较新的数据可用", updateFund: "更新基金数据", updateEquity: "更新股票数据",
    initializeFund: "初始化基金数据", initializeEquity: "初始化中国股票数据", retry: "重试", recover: "继续恢复",
    observed: "状态检查时间", activeRelease: "当前服务版本", completed: "上次更新完成时间", dateCaution: "更新结果不代表所有数据都截至今天；请查看查询结果的观测日期。", fundScope: "中国公募基金", mainlandScope: "中国大陆股票", hongKongScope: "香港股票", checkDate: "数据核查日期",
    noDataScope: "当前数据范围未在有效配置中启用。", configurationUnknown: "暂时无法确认当前数据配置。", serviceReadFailed: "数据服务状态暂时无法刷新；已有配置并未因此改变。请稍后重试。", priorData: "既有已发布数据仍可查询。", stage: "当前阶段", operation: "操作", loading: "正在读取数据状态…",
  },
  en: {
    status: "Data updates", platformReady: "Data service connected", platformUnavailable: "Data service unavailable",
    noUniverse: "No data scope is enabled in the current configuration", configured: "Enabled", disabled: "Disabled",
    unconfigured: "Data not configured", unconfiguredReason: "Establish a current data configuration first.",
    authorityUnset: "Current configuration authority unset", authorityUnsetReason: "Historical configuration material exists, but current effective authority cannot be confirmed and needs attention.",
    configurationUnavailable: "Configuration status unknown", lifecycleUnavailable: "The current data lifecycle status could not be confirmed.",
    ready: "Data available", absent: "No data available yet", initializing: "Loading data for the first time", updating: "Updating",
    recovering: "Resuming an interrupted update", updated: "Last update completed", noChange: "No changes in last update",
    busy: "Another update is running", failed: "Update failed; existing data remains available", failedNoData: "Initialization did not complete; no data is available",
    blocked: "Configuration or action is required before updating", unresolved: "Interrupted state is unresolved", unavailable: "Data is currently unavailable",
    refresh: "Refresh to use current data", newer: "Newer data is available", updateFund: "Update fund data", updateEquity: "Update equity data",
    initializeFund: "Initialize Fund Data", initializeEquity: "Initialize China Equity Data", retry: "Retry", recover: "Resume recovery",
    observed: "Status checked", activeRelease: "Serving release", completed: "Last update completed", dateCaution: "An update outcome does not mean every series is current through today; check the observation dates in query results.", fundScope: "China public funds", mainlandScope: "Mainland China equities", hongKongScope: "Hong Kong equities", checkDate: "Data check date",
    noDataScope: "This data scope is not enabled in the current effective configuration.", configurationUnknown: "Current data configuration could not be confirmed.", serviceReadFailed: "The data service status could not be refreshed. This does not change the last known configuration. Try again later.", priorData: "Previously published data remains queryable.", stage: "Current stage", operation: "Operation", loading: "Reading data status…",
  },
};

let requestRevision = 0;
let productRequestRevision = 0;
let refreshTimer = null;

export function lifecycleCopy(language = state.language) {
  return COPY[language === "en" ? "en" : "zh"];
}

function configScope(scope) {
  return LIFECYCLE_SCOPES[scope] || null;
}

export function configured(scope) {
  const item = configScope(scope);
  const enabled = state.configuration?.enabled_component_ids || state.configuration?.enabled_universes || [];
  return !!item && configurationStatus() === "configured" && enabled.includes(item.componentId);
}

export function configurationStatus() {
  const config = state.configuration;
  const enabled = config?.enabled_component_ids || config?.enabled_universes;
  if (!Array.isArray(enabled)) return "unknown";
  const status = config.scope_status || (config.status === "no_universe_enabled" ? "no_data_scope_enabled" : config.status);
  if (status === "configured") return enabled.length ? "configured" : "unknown";
  if (["unconfigured", "no_data_scope_enabled", "authority_unset"].includes(status)) return enabled.length ? "unknown" : status;
  return "unknown";
}

export function serving(scope) {
  return (state.lifecycle.readback?.serving_by_scope || state.lifecycle.readback?.serving_by_universe)?.[scope] || null;
}

export function latestOperation(scope) {
  return state.lifecycle.readback?.latest_by_scope?.[scope] || null;
}

export function operationFor(scope) {
  const readback = state.lifecycle.readback;
  return readback?.latest_by_scope?.[scope] || null;
}

export function configuredUpdateOperation() {
  const operation = state.lifecycle.readback?.latest_by_scope?.installation || null;
  return operation?.operation_type && operation.operation_type !== "configured_update" ? null : operation;
}

export function configuredUpdateScopes() {
  const values = state.lifecycle.readback?.freshness_by_update_scope || {};
  return Object.entries(values)
    .filter(([scopeId]) => UPDATE_SCOPES[scopeId])
    .map(([scopeId, value]) => ({scopeId, ...UPDATE_SCOPES[scopeId], facts: value}));
}

export function updateScopeAvailability(scopeId) {
  const descriptor = UPDATE_SCOPES[scopeId];
  const component = descriptor ? serving(descriptor.universe) : null;
  if (state.platformHealth?.status !== "ok" || state.configurationReadError || state.lifecycle.error) return {status: "unconfirmed"};
  if (component?.queryable === false) return {status: "unavailable"};
  if (descriptor?.universe === "Fund" && component?.queryable === true) return {status: "available"};
  // Both China Equity markets share one component. Its positive queryability
  // does not establish either market's serving availability or retained data.
  return {status: "unconfirmed"};
}

export function updateScopeState(scopeId) {
  const facts = state.lifecycle.readback?.freshness_by_update_scope?.[scopeId];
  const descriptor = UPDATE_SCOPES[scopeId];
  if (!descriptor || !facts) return {key: "unknown", tone: "muted", facts, availability: {status: "unconfirmed"}};
  const availability = updateScopeAvailability(scopeId);
  if (facts.currently_configured === false) return {key: "disabled", tone: "muted", facts, availability};
  const operation = configuredUpdateOperation();
  if (operation?.status === "running") return {key: "checking", tone: "warn", facts, availability};
  if (operation?.status === "busy") return {key: "busy", tone: "warn", facts, availability};
  if (operation?.status === "blocked") return {key: "blocked", tone: "bad", facts, availability};
  const result = facts.latest_run_result;
  if (result?.result === "failed_check") return {key: availability.status === "unavailable" ? "failed_no_data" : "failed", tone: "bad", facts, availability};
  if (result?.result === "successful_check") return {key: result.material_change ? "checked_changed" : "checked_no_change", tone: "ok", facts, availability};
  return {key: availability.status === "unavailable" ? "absent" : "ready", tone: availability.status === "available" ? "ok" : "muted", facts, availability};
}

export function configuredUpdateState() {
  const operation = configuredUpdateOperation();
  if (!state.lifecycle.readback) return {key: "unknown", tone: "warn", operation};
  if (operation?.status === "running") return {key: "running", tone: "warn", operation};
  if (operation?.status === "busy") return {key: "busy", tone: "warn", operation};
  if (operation?.status === "blocked") return {key: "blocked", tone: "bad", operation};
  if (operation?.status === "failed") {
    const values = Object.values(operation.detail?.scope_results || {});
    const partial = values.some((value) => value?.result === "successful_check") && values.some((value) => value?.result === "failed_check");
    return {key: partial ? "partial" : "failed", tone: partial ? "warn" : "bad", operation};
  }
  if (operation?.status === "no_material_change") return {key: "no_material_change", tone: "ok", operation};
  if (operation?.status === "published") {
    const values = Object.values(operation.detail?.scope_results || {});
    const partial = values.some((value) => value?.result === "failed_check");
    return {key: partial ? "partial" : "published", tone: partial ? "warn" : "ok", operation};
  }
  if (operation?.status === "interrupted_recoverable") return {key: "recovering", tone: "warn", operation};
  if (operation?.status === "interrupted_unresolved") return {key: "blocked", tone: "bad", operation};
  return {key: "ready", tone: "ok", operation};
}

export function operationLabel(scope) {
  const op = operationFor(scope);
  if (!op) return "";
  return String(op.operation_type || op.operation_id || "");
}

function scopeLabel(scope) {
  return scope === "Fund" ? (state.language === "en" ? "Fund" : "基金") : (state.language === "en" ? "Equity" : "股票");
}

function userReason(status, operation, copy) {
  if (status.key === "disabled") return `${copy.noDataScope}${status.serving?.queryable ? ` ${copy.priorData}` : ""}`;
  if (status.key === "unconfigured") return `${copy.unconfiguredReason}${status.serving?.queryable ? ` ${copy.priorData}` : ""}`;
  if (status.key === "no_data_scope_enabled") return `${copy.noUniverse}${status.serving?.queryable ? ` ${copy.priorData}` : ""}`;
  if (status.key === "authority_unset") return `${copy.authorityUnsetReason}${status.serving?.queryable ? ` ${copy.priorData}` : ""}`;
  if (status.key === "configuration_unavailable") return `${copy.configurationUnknown}${status.serving?.queryable ? ` ${copy.priorData}` : ""}`;
  if (status.key === "lifecycle_unavailable") return copy.lifecycleUnavailable;
  if (status.key === "busy") return copy.busy;
  if (status.key === "published" || status.key === "no_material_change") return "";
  if (status.key === "failed") return status.serving?.queryable ? copy.failed : copy.failedNoData;
  if (status.key === "interrupted_unresolved") return copy.unresolved;
  if (status.key === "recovering") return copy.recover;
  if (status.key === "blocked") return operation?.reason_code === "no_data_scope_configured" ? copy.noDataScope : copy.blocked;
  if (status.key === "updating" || status.key === "initializing") return copy.stage;
  return "";
}

export function componentSnapshotDiffers(scope, binding = {}) {
  const current = serving(scope);
  if (!current || !binding) return false;
  const bound = binding.component_snapshot_id || binding.snapshot_id || "";
  return !!bound && !!current.snapshot_id && bound !== current.snapshot_id;
}

export function lifecycleState(scope) {
  const c = lifecycleCopy();
  const current = serving(scope);
  const op = operationFor(scope);
  const configStatus = configurationStatus();
  const enabled = configured(scope);
  if (configStatus === "unknown") return {key: "configuration_unavailable", label: c.configurationUnavailable, tone: "warn", operation: op, serving: current};
  if (configStatus === "authority_unset") return {key: "authority_unset", label: c.authorityUnset, tone: "warn", operation: op, serving: current};
  if (configStatus === "unconfigured") return {key: "unconfigured", label: c.unconfigured, tone: "warn", operation: op, serving: current};
  if (configStatus === "no_data_scope_enabled") return {key: "no_data_scope_enabled", label: c.noUniverse, tone: "muted", operation: op, serving: current};
  if (!enabled) return {key: "disabled", label: c.disabled, tone: "muted", operation: op, serving: current};
  if (!state.lifecycle.readback) return {key: "lifecycle_unavailable", label: c.unavailable, tone: "warn", operation: null, serving: current};
  if (op?.status === "busy") return {key: "busy", label: c.busy, tone: "warn", operation: op, serving: current};
  if (op?.status === "blocked" && op.reason_code !== "no_data_scope_configured") return {key: "blocked", label: c.blocked, tone: "warn", operation: op, serving: current};
  if (op?.status === "interrupted_recoverable") return {key: "recovering", label: c.recovering, tone: "warn", operation: op, serving: current};
  if (op?.status === "interrupted_unresolved") return {key: "interrupted_unresolved", label: c.unresolved, tone: "warn", operation: op, serving: current};
  if (op?.status === "running") return {key: current?.queryable ? "updating" : "initializing", label: current?.queryable ? c.updating : c.initializing, tone: "warn", operation: op, serving: current};
  if (!current?.queryable) {
    if (["failed"].includes(op?.status)) {
      return {key: op.status, label: c.failedNoData, tone: "warn", operation: op, serving: current};
    }
    return {key: "absent", label: c.absent, tone: "warn", operation: op, serving: current};
  }
  if (op?.status === "failed") return {key: "failed", label: c.failed, tone: "warn", operation: op, serving: current};
  if (op?.status === "published") return {key: "published", label: c.updated, tone: "ok", operation: op, serving: current};
  if (op?.status === "no_material_change") return {key: "no_material_change", label: c.noChange, tone: "ok", operation: op, serving: current};
  return {key: "ready", label: c.ready, tone: "ok", operation: op, serving: current};
}

export function canStartUpdate(scope) {
  if (state.platformHealth?.status !== "ok" || !state.lifecycle.readback || state.lifecycle.error || state.configurationReadError || !configured(scope)) return false;
  if (state.lifecycle.pendingScopes?.[scope]) return false;
  const status = lifecycleState(scope);
  if (["updating", "initializing", "busy", "blocked", "interrupted_unresolved", "unknown"].includes(status.key)) return false;
  return status.key !== "failed" || status.operation?.retryable === true;
}

function query(values) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export async function refreshLifecycle({scope = "", boundSnapshotId = "", boundReleaseId = "", silent = false} = {}) {
  const requestId = ++requestRevision;
  if (!silent) setLifecycleState({loading: true, error: null});
  try {
    const readback = await workspaceApi.system.lifecycle({
      scope,
      snapshot_id: boundSnapshotId,
      release_id: boundReleaseId,
    });
    if (requestId < requestRevision) return state.lifecycle.readback;
    if (Number(readback?.revision || 0) < Number(state.lifecycle.revision || 0)) return state.lifecycle.readback;
    setLifecycleState({readback, revision: Number(readback?.revision || 0), observedAt: readback?.observed_at_utc || null, loading: false, error: null});
    return readback;
  } catch (error) {
    if (requestId >= requestRevision) setLifecycleState({loading: false, error});
    throw error;
  }
}

export async function refreshProductLifecycle() {
  const requestId = ++productRequestRevision;
  const results = await Promise.allSettled([
    workspaceApi.system.health(),
    workspaceApi.system.readiness(),
    workspaceApi.system.configuration(),
    workspaceApi.system.lifecycle(),
  ]);
  if (requestId !== productRequestRevision) return {health: state.platformHealth, readiness: state.readiness, configuration: state.configuration, lifecycle: state.lifecycle.readback, configurationFresh: false, lifecycleFresh: false};
  state.platformHealth = results[0].status === "fulfilled" ? results[0].value : null;
  if (results[1].status === "fulfilled") state.readiness = results[1].value;
  if (results[2].status === "fulfilled") state.configuration = results[2].value;
  state.configurationReadError = results[2].status === "rejected" ? results[2].reason : null;
  if (results[3].status === "fulfilled") {
    const value = results[3].value;
    if (Number(value?.revision || 0) >= Number(state.lifecycle.revision || 0)) {
      setLifecycleState({readback: value, revision: Number(value?.revision || 0), observedAt: value?.observed_at_utc || null, loading: false, error: null});
    }
  }
  const failure = results[3].status === "rejected" ? results[3] : null;
  if (failure) setLifecycleState({loading: false, error: failure.reason});
  else setLifecycleState({}); // Configuration-only changes must also repaint the shared surface.
  if (Object.values(state.lifecycle.readback?.latest_by_scope || {}).some((operation) => operation?.status === "running")) scheduleLifecycleRefresh(1000);
  return {health: state.platformHealth, readiness: state.readiness, configuration: state.configuration, lifecycle: state.lifecycle.readback, configurationFresh: results[2].status === "fulfilled", lifecycleFresh: results[3].status === "fulfilled"};
}

export function scheduleLifecycleRefresh(delay = 250) {
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(async () => {
    refreshTimer = null;
    try {
      const readback = await refreshLifecycle({silent: true});
      const running = Object.values(readback?.latest_by_scope || {}).some((operation) => operation?.status === "running");
      if (running) scheduleLifecycleRefresh(1000);
    } catch { /* focus/visibility refresh remains available after a transient failure */ }
  }, delay);
}

export async function runDataScopeUpdate(scope) {
  const item = configScope(scope);
  if (!item) throw new Error(`Unsupported update scope: ${scope}`);
  const product = await refreshProductLifecycle();
  if (!product.configurationFresh || !product.lifecycleFresh || !state.lifecycle.readback) throw state.lifecycle.error || new Error("Current configuration or operation lifecycle readback is unavailable");
  if (["unknown", "authority_unset"].includes(configurationStatus())) throw new Error("Current effective data configuration authority is not confirmed");
  if (!configured(scope)) {
    const blocked = {status: "blocked", reason_code: "no_data_scope_configured", scope};
    setLifecycleState({pendingScopes: {...state.lifecycle.pendingScopes, [scope]: null}});
    await refreshLifecycle({scope}).catch(() => {});
    return blocked;
  }
  const before = latestOperation(scope);
  if (["running", "busy", "interrupted_unresolved"].includes(before?.status) || (before?.status === "blocked" && before.reason_code !== "no_data_scope_configured")) return before;
  if (state.lifecycle.pendingScopes?.[scope]) return before;
  setLifecycleState({pendingScopes: {...state.lifecycle.pendingScopes, [scope]: true}});
  scheduleLifecycleRefresh(250);
  let response;
  let requestError = null;
  try {
    response = scope === "Fund" ? await workspaceApi.funds.update() : await workspaceApi.equity.update();
  } catch (error) {
    requestError = error;
  }
  let readback = null;
  try { readback = await refreshLifecycle({scope}); } catch { /* preserve the original request error */ }
  setLifecycleState({pendingScopes: {...state.lifecycle.pendingScopes, [scope]: false}});
  if (requestError) {
    const current = readback?.latest_by_scope?.[scope];
    if (current && current.operation_id !== before?.operation_id && ["running", "published", "no_material_change", "failed", "busy", "blocked", "interrupted_recoverable", "interrupted_unresolved"].includes(current.status)) {
      return {...current, response_lost: true};
    }
    throw requestError;
  }
  return readback?.latest_by_scope?.[scope] || response || null;
}

export function canStartConfiguredUpdate() {
  if (state.platformHealth?.status !== "ok" || !state.lifecycle.readback || state.lifecycle.error || state.configurationReadError || configurationStatus() !== "configured") return false;
  if (state.lifecycle.pendingConfiguredUpdate) return false;
  return !["running", "blocked", "recovering"].includes(configuredUpdateState().key);
}

export async function runConfiguredUpdate() {
  const product = await refreshProductLifecycle();
  if (!product.configurationFresh || !product.lifecycleFresh || !state.lifecycle.readback) throw state.lifecycle.error || new Error("Current configuration or operation lifecycle readback is unavailable");
  if (configurationStatus() !== "configured") throw new Error("Current effective data configuration is not ready for Update");
  const before = configuredUpdateOperation();
  if (["running", "blocked", "recovering"].includes(configuredUpdateState().key)) return before;
  setLifecycleState({pendingConfiguredUpdate: true});
  scheduleLifecycleRefresh(250);
  let response = null;
  let requestError = null;
  try { response = await workspaceApi.system.update(); } catch (error) { requestError = error; }
  let readback = null;
  try { readback = await refreshLifecycle({silent: true}); } catch { /* preserve request error */ }
  setLifecycleState({pendingConfiguredUpdate: false});
  const current = readback?.latest_by_scope?.installation;
  if (requestError) {
    if (current && current.operation_id !== before?.operation_id) return {...current, response_lost: true};
    throw requestError;
  }
  return current || response || null;
}

export function renderLifecycleSurface({compact = false, includeActions = false, scopes = ["Fund", "Equity"]} = {}) {
  const c = lifecycleCopy();
  const platformReady = state.platformHealth?.status === "ok";
  const serviceIssue = !platformReady || state.configurationReadError || state.lifecycle.error;
  const config = state.configuration || {};
  const configStatus = configurationStatus();
  const enabled = configStatus === "configured" ? (config.enabled_component_ids || config.enabled_universes) : [];
  const cards = scopes.map((scope) => {
    const meta = configScope(scope);
    const status = serviceIssue ? {key: "lifecycle_unavailable", label: c.lifecycleUnavailable, tone: "warn", operation: null, serving: null} : lifecycleState(scope);
    const op = status.operation || {};
    const pending = !!state.lifecycle.pendingScopes?.[scope];
    const label = status.key === "recovering" ? c.recover : status.key === "failed" ? c.retry : scope === "Fund" ? (status.key === "absent" ? c.initializeFund : c.updateFund) : (status.key === "absent" ? c.initializeEquity : c.updateEquity);
    const actionable = canStartUpdate(scope);
    const action = includeActions && meta && configured(scope) ? `<button class="btn" data-lifecycle-update="${scope}" ${actionable ? "" : "disabled"}>${escapeHtml(label)}</button>` : "";
    const reason = userReason(status, op, c);
    return `<article class="card lifecycle-card" data-lifecycle-scope="${scope}"><div class="card-top"><strong>${escapeHtml(scopeLabel(scope))}</strong><span class="tag ${status.tone}">${escapeHtml(status.label)}</span></div>${reason?`<p>${escapeHtml(reason)}</p>`:""}${op.completed_at_utc?`<small>${escapeHtml(c.completed)}: ${escapeHtml(op.completed_at_utc.slice(0,10))}</small>`:""}${["updating", "initializing"].includes(status.key) ? `<div class="lifecycle-stage"><b>${escapeHtml(c.stage)}</b> ${escapeHtml(status.label)}</div>` : ""}<div class="actions">${action}</div></article>`;
  }).join("");
  const configurationLabel = enabled.map((key) => key === "CN_PUBLIC_FUND" ? (state.language === "en" ? "Fund" : "基金") : key === "CN_A_SHARE" ? (state.language === "en" ? "Equity" : "股票") : key).join(" · ");
  const configurationText = serviceIssue ? c.serviceReadFailed : configStatus === "configured" ? `${c.configured}: ${configurationLabel}` : configStatus === "unconfigured" ? `${c.unconfigured} — ${c.unconfiguredReason}` : configStatus === "no_data_scope_enabled" ? c.noUniverse : configStatus === "authority_unset" ? c.authorityUnsetReason : c.configurationUnknown;
  const shell = `<section class="product-section lifecycle-surface ${compact ? "compact" : ""}"><div class="section-head"><div><div class="eyebrow">${escapeHtml(c.status)}</div><h2>${escapeHtml(platformReady ? c.platformReady : c.platformUnavailable)}</h2><p>${escapeHtml(configurationText)}</p></div></div><div class="lifecycle-grid">${cards}</div><p class="lifecycle-caution">${escapeHtml(c.dateCaution)}</p><details class="product-advanced"><summary>${escapeHtml(c.observed)}</summary><code>${escapeHtml(state.lifecycle.observedAt || "—")}</code></details></section>`;
  return shell;
}

export function bindLifecycleActions(onUpdate = runDataScopeUpdate) {
  document.querySelectorAll("[data-lifecycle-update]").forEach((button) => button.addEventListener("click", async () => {
    const scope = button.dataset.lifecycleUpdate;
    button.disabled = true;
    try { await onUpdate(scope); } finally { scheduleLifecycleRefresh(0); }
  }));
}
