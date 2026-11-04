import {escapeHtml} from "./components.js";
import {lifecycleState} from "./lifecycle.js";
import {state} from "./state.js";

const COPY = {
  zh: {title:"数据",subtitle:"从金融对象进入数据。可用范围因对象、指标和期间而异。",fund:"基金",equity:"股票",fundScope:"中国公募基金",equityScope:"已验证的中国市场股票（香港范围取决于本机数据）",fundDetail:"按名称或代码查找基金与份额类别",equityDetail:"按名称、代码或别名查找上市股票",available:"可查询",unavailable:"暂不可查询",unknown:"状态待确认",open:"查找",foot:"此处不提供整个市场的统一最新日期。请在具体查询结果中查看返回观测日期。"},
  en: {title:"Data",subtitle:"Start with a financial object. Availability varies by object, measure and period.",fund:"Funds",equity:"Equities",fundScope:"China public funds",equityScope:"Validated China-market equities (Hong Kong where configured)",fundDetail:"Find funds and share classes by name or code",equityDetail:"Find listings by name, code or recorded alias",available:"Queryable",unavailable:"Not queryable",unknown:"Status unconfirmed",open:"Find",foot:"There is no single proven latest date for an entire market here. Check returned observation dates in each result."},
};

function directoryRow(name, scope, detail, universe, href, x) {
  const serviceFresh = state.platformHealth?.status === "ok" && !state.configurationReadError && !state.lifecycle.error;
  const queryable = serviceFresh ? lifecycleState(universe).serving?.queryable : null;
  const status = queryable === true ? x.available : queryable === false ? x.unavailable : x.unknown;
  return `<article class="directory-row"><div><h2>${escapeHtml(name)}</h2><p>${escapeHtml(detail)}</p></div><div class="directory-scope">${escapeHtml(scope)}</div><div class="directory-status"><span class="status-pill ${queryable === true ? "ok" : queryable === false ? "warn" : "muted"}">${escapeHtml(status)}</span></div><a href="${href}">${escapeHtml(x.open)} →</a></article>`;
}

export function renderUserDataCatalogPage() {
  const x = COPY[state.language] || COPY.zh;
  document.getElementById("workspace-main").innerHTML = `<div class="page data-page"><header class="page-header"><div class="eyebrow">Financial Research</div><h1>${escapeHtml(x.title)}</h1><p>${escapeHtml(x.subtitle)}</p></header><div class="data-directory"><div class="directory-row directory-head"><span>${escapeHtml(x.title)}</span><span>${state.language === "en" ? "Coverage" : "当前范围"}</span><span>${state.language === "en" ? "Availability" : "可用状态"}</span><span></span></div>${directoryRow(x.fund,x.fundScope,x.fundDetail,"Fund","#/data/fund/china-public",x)}${directoryRow(x.equity,x.equityScope,x.equityDetail,"Equity","#/data/equity/china",x)}</div><p class="data-footnote">${escapeHtml(x.foot)}</p></div>`;
}
