import {escapeHtml} from "../components.js";
import {configurationStatus, lifecycleState} from "../lifecycle.js";
import {state} from "../state.js";

const COPY = {
  zh: {lead:"查找可信的金融数据，并在同一环境中开展统计研究。", scope:"当前数据", fund:"基金", equity:"股票", available:"可查询", unavailable:"暂不可查询", unknown:"状态尚未确认", note:"可查询不代表每项数据都更新到今天；实际观测日期以具体查询结果为准。", service:"暂时无法确认数据服务状态，请稍后重试。", serviceAction:"查看数据状态", noConfig:"尚未配置数据范围。请先完成安装配置；此页面不提供配置编辑。", noScope:"当前配置尚未启用基金或股票数据范围。", noData:"尚无可用数据。已配置的范围可分别进行首次载入。", noDataAction:"前往数据更新", partial:"部分数据暂不可用；其他可查询数据仍可继续使用。", failed:"上次数据更新未完成；现有可用数据不受影响。", failedAction:"查看更新情况"},
  en: {lead:"Find governed financial data and use it for statistical research in one place.", scope:"Data available here", fund:"Funds", equity:"Equities", available:"Queryable", unavailable:"Not queryable", unknown:"Status not confirmed", note:"Queryable does not mean every measure is current through today. Check the observation dates in each result.", service:"The data service status could not be confirmed. Try again later.", serviceAction:"View Data Status", noConfig:"No data scope is configured. Complete installation configuration first; this page does not edit it.", noScope:"The current configuration has no enabled Fund or Equity data scope.", noData:"No data is available yet. Each configured scope can be loaded separately.", noDataAction:"Open Data Update", partial:"Some data is unavailable; other queryable data remains usable.", failed:"The last data update did not complete; existing available data remains usable.", failedAction:"Review Data Update"},
};

export function renderOverview() {
  const x = COPY[state.language] || COPY.zh;
  const scopes = [["Fund",x.fund],["Equity",x.equity]].map(([scope,label]) => ({scope,label,status:lifecycleState(scope)}));
  const servingFresh = state.platformHealth?.status === "ok" && !state.configurationReadError && !state.lifecycle.error;
  const availableCount = servingFresh ? scopes.filter(({status}) => status.serving?.queryable === true).length : 0;
  const config = configurationStatus();
  const failed = scopes.some(({status}) => status.key === "failed");
  let warning = "", action = "", target = "";
  if (!servingFresh) {warning=x.service;action=x.serviceAction;target="#/settings/data-status";}
  else if (config === "unconfigured" || config === "authority_unset") warning=x.noConfig;
  else if (config === "no_data_scope_enabled") warning=x.noScope;
  else if (!availableCount) {warning=x.noData;action=x.noDataAction;target="#/settings/data-update";}
  else if (failed) {warning=x.failed;action=x.failedAction;target="#/settings/data-update";}
  else if (availableCount < scopes.length) {warning=x.partial;action=x.serviceAction;target="#/settings/data-status";}
  const statusRows = scopes.map(({label,status}) => {
    const queryable = servingFresh ? status.serving?.queryable : null;
    const value = queryable === true ? x.available : queryable === false ? x.unavailable : x.unknown;
    return `<div class="home-scope"><span>${escapeHtml(label)}</span><span class="status-pill ${queryable === true ? "ok" : queryable === false ? "warn" : "muted"}">${escapeHtml(value)}</span></div>`;
  }).join("");
  document.getElementById("workspace-main").innerHTML = `<div class="page home-page"><section class="home-intro"><div class="eyebrow">Financial Research</div><h1>Financial Research</h1><p>${escapeHtml(x.lead)}</p></section>${warning ? `<div class="notice" role="status"><strong>${escapeHtml(warning)}</strong>${action ? `<br><a class="context-action" href="${target}">${escapeHtml(action)} →</a>` : ""}</div>` : ""}<section class="home-readout"><h2>${escapeHtml(x.scope)}</h2><div class="home-scope-list">${statusRows}</div><p class="home-note">${escapeHtml(x.note)}</p></section></div>`;
}
