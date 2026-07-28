import{escapeHtml,head}from"../components.js";
import{state}from"../state.js";
const GROUPS=[
  {id:"research",title:"Research",description:"Start market, company and diagnostic modeling workflows.",apps:["modeling_workbench","market_monitor","company_research"]},
  {id:"evidence",title:"Evidence",description:"Open governed report and PDF evidence entry points.",apps:["reports_pdf"]},
  {id:"workspace",title:"Workspace",description:"Manage saved dashboard workspaces.",apps:["research_dashboards"]},
  {id:"operations",title:"Operations",description:"Review source status and safe update previews.",apps:["operations"]},
  {id:"future_extension",title:"Future Extensions",description:"Reserved extension points remain disabled until reviewed.",apps:["external_plugin_placeholder"]},
];
function appCard(app){const stateClass=app.enabled?"ok":"warn",action=app.enabled?`<button class="btn" data-open-app="${escapeHtml(app.route)}">Open</button>`:'<button class="btn" disabled>Disabled</button>';return`<article class="card app-card ${app.enabled?"":"disabled-card"}"><div class="eyebrow">${escapeHtml(app.app_category)} / ${escapeHtml(app.entry_type)}</div><h3>${escapeHtml(app.app_name)}</h3><p>${escapeHtml(app.description)}</p><div class="app-card-foot"><span class="tag ${stateClass}">${escapeHtml(app.status)}</span>${action}</div></article>`}
export function renderApps(){const byId=new Map(state.apps.map((app)=>[app.app_id,app])),sections=GROUPS.map((group)=>{const apps=group.apps.map((id)=>byId.get(id)).filter(Boolean);return`<section class="product-section" data-app-group="${escapeHtml(group.id)}"><div class="section-head"><div><h2>${escapeHtml(group.title)}</h2><p>${escapeHtml(group.description)}</p></div></div><div class="app-grid">${apps.map(appCard).join("")}</div></section>`}).join("");document.getElementById("workspace-main").innerHTML=head("Apps","Apps","Functional entry points for research, evidence, workspace and operations. Apps are separate from Plug-ins and research Dashboards.")+sections}
