import {escapeHtml} from "../components.js";
import {configurationStatus, configuredUpdateScopes, configuredUpdateState, updateScopeState} from "../lifecycle.js";
import {state} from "../state.js";

const COPY = {
  zh: {title: "数据状态", lead: "查看各金融范围的核查结果和最近一次成功核查日期。", available: "数据服务可用", unavailable: "数据服务暂不可用", unknown: "可用性待确认", unknownCheck: "暂无本范围核查记录", disabled: "未启用", checked: "数据核查日期", latest: "最近一次核查", successful: "核查成功", changed: "已发布变化", changeUnconfirmed: "发现变化，发布尚未确认", unchanged: "无变化可发布", failed: "本次核查失败", retained: "仍使用上次已验证数据", serviceOnly: "现有数据服务可用；此范围的既往核查日期尚未得到证明", marketUnknown: "此市场的现有数据可用性尚未得到确认。", disabledMarketUnknown: "此范围未启用更新；现有市场数据可用性尚未得到确认。", noData: "当前没有已验证的可用数据", notProven: "暂无可证明日期", config: "当前数据配置尚未确认。", service: "暂时无法连接或刷新数据服务。下方核查记录可能是上次读取的状态；当前可用性待确认。请稍后重试。", note: "数据核查日期不是最新交易日、净值观测日或报告期；具体结果的观测日期请在基金或股票查询中查看。", technical: "技术状态", fundScope: "中国公募基金", mainlandScope: "中国大陆股票", hongKongScope: "香港股票"},
  en: {title: "Data Status", lead: "See the latest check outcome and successful check date for each financial scope.", available: "Data service available", unavailable: "Data service unavailable", unknown: "Availability unconfirmed", unknownCheck: "No check recorded for this scope", disabled: "Not enabled", checked: "Data check date", latest: "Latest check", successful: "Check succeeded", changed: "Change published", changeUnconfirmed: "Change found; publication unconfirmed", unchanged: "No publishable change", failed: "This check failed", retained: "The last validated data remains in use", serviceOnly: "Existing data service is available; a prior check date for this scope is not proven", marketUnknown: "Current data availability for this market is unconfirmed.", disabledMarketUnknown: "This scope is not enabled for updates; existing market data availability is unconfirmed.", noData: "No validated data is currently available", notProven: "No proven date", config: "The current data configuration could not be confirmed.", service: "The data service could not be reached or refreshed. Check records below may be from the last read; current availability is unconfirmed. Try again later.", note: "The data check date is not the latest trading day, NAV observation date or report period. See the observation date in each Fund or Equity result.", technical: "Technical status", fundScope: "China public funds", mainlandScope: "Mainland China equities", hongKongScope: "Hong Kong equities"},
};

function dateValue(fact, x) {
  if (fact?.status !== "available" || !fact.value) return x.notProven;
  const parsed = new Date(fact.value);
  if (Number.isNaN(parsed.getTime())) return x.notProven;
  return new Intl.DateTimeFormat(state.language === "en" ? "en-US" : "zh-CN", {year: "numeric", month: "short", day: "numeric"}).format(parsed);
}

function row(scope, copy) {
  const value = updateScopeState(scope.scopeId);
  const availabilityStatus = value.availability?.status;
  const facts = scope.facts || {};
  const result = facts.latest_run_result;
  const availability = value.key === "disabled" ? copy.disabled : availabilityStatus === "available" ? copy.available : availabilityStatus === "unavailable" ? copy.unavailable : copy.unknown;
  const published = configuredUpdateState().operation?.status === "published";
  const latest = value.key === "disabled" ? copy.disabled : result?.result === "successful_check" ? (result.material_change ? (published ? copy.changed : copy.changeUnconfirmed) : copy.unchanged) : result?.result === "failed_check" ? copy.failed : copy.unknownCheck;
  const priorScopeCheck = facts.last_checked?.status === "available";
  const note = value.key === "disabled" ? (availabilityStatus === "unconfirmed" ? copy.disabledMarketUnknown : availabilityStatus === "available" ? (priorScopeCheck ? copy.retained : copy.serviceOnly) : "") : result?.result === "failed_check" ? (availabilityStatus === "unconfirmed" ? copy.marketUnknown : availabilityStatus === "available" ? (priorScopeCheck ? copy.retained : copy.serviceOnly) : copy.noData) : result?.result === "successful_check" ? copy.successful : "";
  return `<section class="section status-scope-card"><div class="section-heading"><h2>${escapeHtml(copy[scope.labelKey])}</h2><span class="status-pill ${value.key === "disabled" ? "muted" : availabilityStatus === "available" ? "ok" : availabilityStatus === "unavailable" ? "warn" : "muted"}">${escapeHtml(availability)}</span></div><div class="status-facts"><div><span>${escapeHtml(copy.checked)}</span><strong>${escapeHtml(dateValue(facts.last_checked, copy))}</strong></div><div><span>${escapeHtml(copy.latest)}</span><strong>${escapeHtml(latest)}</strong></div></div>${note ? `<p class="settings-note">${escapeHtml(note)}</p>` : ""}</section>`;
}

export function renderDataStatus() {
  const copy = COPY[state.language] || COPY.zh;
  const scopes = configuredUpdateScopes();
  const serviceIssue = state.platformHealth?.status !== "ok" || state.configurationReadError || state.lifecycle.error;
  const statusContent = configurationStatus() !== "configured" ? `<div class="notice">${escapeHtml(copy.config)}</div>` : scopes.length ? scopes.map((scope) => row(scope, copy)).join("") : `<div class="notice">${escapeHtml(copy.unknown)}</div>`;
  const content = `${serviceIssue ? `<div class="risk" role="alert">${escapeHtml(copy.service)}</div>` : ""}${serviceIssue && !state.configuration ? "" : statusContent}`;
  document.getElementById("workspace-main").innerHTML = `<div class="page settings-page"><nav class="breadcrumbs"><span>${state.language === "en" ? "Settings" : "设置"}</span><span>›</span><span>${escapeHtml(copy.title)}</span></nav><header class="page-header"><h1>${escapeHtml(copy.title)}</h1><p>${escapeHtml(copy.lead)}</p></header>${content}<p class="settings-note">${escapeHtml(copy.note)}</p><details class="technical-detail"><summary>${escapeHtml(copy.technical)}</summary><div class="detail-body"><code>${escapeHtml(state.lifecycle.readback?.revision ?? "—")}</code> · <code>${escapeHtml(state.lifecycle.observedAt || "—")}</code></div></details></div>`;
}
