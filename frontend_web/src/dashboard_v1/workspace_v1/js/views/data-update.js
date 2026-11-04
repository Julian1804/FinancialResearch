import {formatApiError} from "../api.js";
import {escapeHtml} from "../components.js";
import {canStartConfiguredUpdate, configurationStatus, configuredUpdateScopes, configuredUpdateState, runConfiguredUpdate, scheduleLifecycleRefresh, updateScopeState} from "../lifecycle.js";
import {captureRouteVisit, ownsRouteVisit, state} from "../state.js";

const COPY = {
  zh: {
    title: "更新数据", lead: "一次核查当前配置的数据范围。更新期间，已确认可用的数据仍可继续查询。", update: "核查并更新数据", checking: "正在核查数据…", ready: "可以开始核查", published: "核查完成，数据已更新", partial: "部分完成", noChange: "核查完成，无需更新", failed: "核查失败", busy: "另一个更新正在进行", blocked: "当前更新被阻止", recovering: "正在恢复中断的更新", unknown: "暂时无法确认更新状态", notConfigured: "当前数据配置尚未准备好，暂时不能开始更新。", scopeResult: "本次核查结果", successful: "核查成功", changed: "已发布变化", changeUnconfirmed: "发现变化，发布尚未确认", unchanged: "未发现需要发布的变化", failedScope: "本次核查失败", retained: "仍使用上次已验证数据", serviceOnly: "现有数据服务可用；此范围的既往核查日期尚未得到证明", marketUnknown: "此市场的现有数据可用性尚未得到确认。", disabledMarketUnknown: "此范围未启用更新；现有市场数据可用性尚未得到确认。", noData: "当前没有已验证的可用数据", disabled: "当前范围未启用", fundScope: "中国公募基金", mainlandScope: "中国大陆股票", hongKongScope: "香港股票", checkDate: "数据核查日期", notProven: "暂无可证明日期", note: "数据核查日期表示最近一次成功完成该范围所需检查的日期，不是最新交易日或净值观测日。", error: "更新请求未完成", service: "暂时无法连接或刷新数据服务。下方核查记录可能是上次读取的状态；当前可用性待确认，请稍后重试。", sourceFailure: "所需数据源核查未完成。请稍后重试；若持续失败，请联系维护人员。", fundFailure: "所需基金数据核查未完成。请稍后重试；若持续失败，请联系维护人员。", otherFailure: "此范围未能完成验证。请稍后重试；若持续失败，请联系维护人员。", partialAction: "部分范围已完成；失败范围尚未完成本次核查。请查看下方结果并稍后重试。", failedAction: "更新未完成，新数据尚未得到确认。请查看失败范围并稍后重试；若持续失败，请联系维护人员。", technical: "技术详情", noScopes: "当前配置的金融数据范围尚未得到确认"},
  en: {
    title: "Data Update", lead: "Check the data scopes in the current configuration in one action. Data confirmed as available remains queryable during the check.", update: "Check and update data", checking: "Checking data…", ready: "Ready to check", published: "Check complete; data updated", partial: "Partially complete", noChange: "Check complete; no update was needed", failed: "Check failed", busy: "Another update is already running", blocked: "This update is blocked", recovering: "Resuming an interrupted update", unknown: "Update status cannot be confirmed", notConfigured: "The current data configuration is not ready, so an update cannot start.", scopeResult: "This check", successful: "Check succeeded", changed: "Change published", changeUnconfirmed: "Change found; publication unconfirmed", unchanged: "No publishable change was found", failedScope: "This check failed", retained: "The last validated data remains in use", serviceOnly: "Existing data service is available; a prior check date for this scope is not proven", marketUnknown: "Current data availability for this market is unconfirmed.", disabledMarketUnknown: "This scope is not enabled for updates; existing market data availability is unconfirmed.", noData: "No validated data is currently available", disabled: "This scope is not enabled", fundScope: "China public funds", mainlandScope: "Mainland China equities", hongKongScope: "Hong Kong equities", checkDate: "Data check date", notProven: "No proven date", note: "The data check date is the last successful completion date for the required checks in this scope. It is not the latest trading day or NAV observation date.", error: "The update request did not complete", service: "The data service could not be reached or refreshed. Check records below may be from the last read; current availability is unconfirmed. Try again later.", sourceFailure: "A required data-source check did not finish. Retry later; if it keeps failing, contact support.", fundFailure: "The required Fund data check did not finish. Retry later; if it keeps failing, contact support.", otherFailure: "This scope could not be verified. Retry later; if it keeps failing, contact support.", partialAction: "Some scopes completed; the failed scope was not refreshed. Review its result below and retry later.", failedAction: "The update did not complete; no new data is confirmed. Review failed scopes and retry later. If it keeps failing, contact support.", technical: "Technical details", noScopes: "The configured financial data scopes could not be confirmed"},
};

let lastError = null;

function dateValue(fact, x) {
  if (fact?.status !== "available" || !fact.value) return x.notProven;
  const parsed = new Date(fact.value);
  if (Number.isNaN(parsed.getTime())) return x.notProven;
  return new Intl.DateTimeFormat(state.language === "en" ? "en-US" : "zh-CN", {year: "numeric", month: "short", day: "numeric"}).format(parsed);
}

function failureAdvice(result, copy) {
  if (result?.reason === "required_market_source_route_incomplete") return copy.sourceFailure;
  if (result?.reason === "required_fund_source_refresh_incomplete") return copy.fundFailure;
  return copy.otherFailure;
}

function scopeRow(scope, copy, serviceIssue = false) {
  const value = updateScopeState(scope.scopeId);
  const facts = scope.facts || {};
  const availabilityStatus = value.availability?.status;
  const published = configuredUpdateState().operation?.status === "published";
  const priorScopeCheck = facts.last_checked?.status === "available";
  const detail = value.key === "disabled" ? (availabilityStatus === "unconfirmed" ? copy.disabledMarketUnknown : availabilityStatus === "available" ? (priorScopeCheck ? copy.retained : copy.serviceOnly) : "") : value.key === "failed" || value.key === "failed_no_data" ? `${failureAdvice(facts.latest_run_result, copy)} ${availabilityStatus === "unconfirmed" ? copy.marketUnknown : availabilityStatus === "available" ? (priorScopeCheck ? copy.retained : copy.serviceOnly) : copy.noData}` : value.key === "checked_changed" ? (published ? copy.changed : copy.changeUnconfirmed) : value.key === "checked_no_change" ? copy.unchanged : "";
  const label = serviceIssue ? copy.unknown : value.key === "disabled" ? copy.disabled : value.key === "failed" || value.key === "failed_no_data" ? copy.failedScope : value.key === "checked_changed" || value.key === "checked_no_change" ? copy.successful : value.key === "checking" ? copy.checking : value.key === "ready" ? copy.ready : value.key === "absent" ? copy.noData : copy.unknown;
  return `<article class="status-row update-scope-row"><div><h2>${escapeHtml(copy[scope.labelKey])}</h2><span class="status-pill ${escapeHtml(value.tone)}">${escapeHtml(label)}</span></div><div><span>${escapeHtml(copy.checkDate)}</span><strong>${escapeHtml(dateValue(facts.last_checked, copy))}</strong></div><p>${escapeHtml(detail)}</p></article>`;
}

function updateSummary(value, copy) {
  return ({ready: copy.ready, running: copy.checking, published: copy.published, partial: copy.partial, no_material_change: copy.noChange, failed: copy.failed, busy: copy.busy, blocked: copy.blocked, recovering: copy.recovering, unknown: copy.unknown}[value.key] || copy.unknown);
}

export function renderDataUpdate() {
  const copy = COPY[state.language] || COPY.zh;
  const updateState = configuredUpdateState();
  if (lastError && updateState.operation?.operation_id && updateState.operation.operation_id !== lastError.operationId) lastError = null;
  const scopes = configuredUpdateScopes();
  const configReady = configurationStatus() === "configured";
  const serviceIssue = state.platformHealth?.status !== "ok" || state.configurationReadError || state.lifecycle.error;
  const canStart = canStartConfiguredUpdate();
  const pending = state.lifecycle.pendingConfiguredUpdate;
  const actionLabel = pending || updateState.key === "running" ? copy.checking : updateState.key === "busy" ? (state.language === "en" ? "Try again" : "重试核查") : copy.update;
  const error = lastError ? `<div class="risk" role="alert"><strong>${escapeHtml(copy.error)}</strong><p>${escapeHtml(formatApiError(lastError.error, state.language))}</p><details class="technical-detail"><summary>${escapeHtml(copy.technical)}</summary><code>${escapeHtml(formatApiError(lastError.error, state.language, true))}</code></details></div>` : "";
  const scopeContent = !configReady ? (serviceIssue ? "" : `<div class="notice">${escapeHtml(copy.notConfigured)}</div>`) : scopes.length ? scopes.map((scope) => scopeRow(scope, copy, serviceIssue)).join("") : `<div class="notice">${escapeHtml(copy.noScopes)}</div>`;
  const guidance = serviceIssue ? (state.language === "en" ? "Retry when the data service is available." : "数据服务恢复后再重试。") : updateState.key === "partial" ? copy.partialAction : updateState.key === "failed" ? copy.failedAction : configReady ? copy.note : copy.notConfigured;
  document.getElementById("workspace-main").innerHTML = `<div class="page settings-page"><nav class="breadcrumbs"><span>${state.language === "en" ? "Settings" : "设置"}</span><span>›</span><span>${escapeHtml(copy.title)}</span></nav><header class="page-header"><h1>${escapeHtml(copy.title)}</h1><p>${escapeHtml(copy.lead)}</p></header>${serviceIssue ? `<div class="risk" role="alert">${escapeHtml(copy.service)}</div>` : ""}${error}<section class="update-action-card"><div><div class="eyebrow">${escapeHtml(copy.scopeResult)}</div><h2>${escapeHtml(serviceIssue ? copy.unknown : updateSummary(updateState, copy))}</h2><p>${escapeHtml(guidance)}</p></div><button class="btn" type="button" data-configured-update ${canStart && configReady && !pending ? "" : "disabled"}>${escapeHtml(actionLabel)}</button></section><div class="status-table">${scopeContent}</div>${guidance === copy.note ? "" : `<p class="settings-note">${escapeHtml(copy.note)}</p>`}</div>`;
  const button = document.querySelector("[data-configured-update]");
  if (button) button.addEventListener("click", async () => {
    const visit = captureRouteVisit("/settings/data-update");
    lastError = null;
    button.disabled = true;
    try { await runConfiguredUpdate(); } catch (errorValue) {
      if (ownsRouteVisit(visit)) lastError = {error: errorValue, operationId: configuredUpdateState().operation?.operation_id || null};
    } finally {
      scheduleLifecycleRefresh(0);
      if (ownsRouteVisit(visit)) renderDataUpdate();
    }
  });
}
