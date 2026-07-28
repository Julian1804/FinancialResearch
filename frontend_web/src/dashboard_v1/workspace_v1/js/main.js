import{bindAiBridge,copyContext,exportContext,populateContextDashboards,setContextDashboard,setContextFormat}from"./ai-bridge.js";
import{workspaceApi}from"./api.js";
import{escapeHtml}from"./components.js";
import{renderDashboardSubnav}from"./dashboard-nav.js";
import{bindNavigation,openView,workspaceSearch}from"./navigation.js";
import{bindPanelResizers}from"./layout.js";
import{state}from"./state.js";
import{updateChromeLanguage}from"./i18n.js";
import{openDashboardDetail,openDashboardTab}from"./views/dashboard-detail.js";
import{openInvestmentSample,renderDataShellPreview}from"./views/data-shell-preview.js";
import{renderModuleDetail}from"./views/module-detail.js";
import{openProjectDetail}from"./views/projects.js";
function bindLanguageToggle(){const saved=localStorage.getItem("fr_workspace_language");if(saved==="en"||saved==="zh")state.language=saved;updateChromeLanguage();document.querySelectorAll("[data-language]").forEach((button)=>button.addEventListener("click",()=>{state.language=button.dataset.language||"zh";localStorage.setItem("fr_workspace_language",state.language);updateChromeLanguage();openView(state.activeView||"overview")}))}
async function boot(){try{const[workspace,projects,products,sources,token,build]=await workspaceApi.bootstrap();state.apps=workspace.apps.apps||[];state.dashboards=workspace.dashboards.dashboards||[];state.archivedDashboards=workspace.dashboards.archived_dashboards||[];state.modules=workspace.modules.modules||[];state.userWorkspace={...(workspace.user_workspace?.state||state.userWorkspace),versions:workspace.user_workspace?.versions||[]};state.projects=projects.projects||[];state.products=products.products||{};state.sources=sources.sources||{};state.token=token||{};document.getElementById("build-version").textContent="版本已加载";renderDashboardSubnav();populateContextDashboards();openView("overview")}catch(error){document.getElementById("workspace-main").innerHTML=`<div class="empty">Workspace bootstrap failed: ${escapeHtml(error)}</div>`}}
bindNavigation();bindAiBridge();bindPanelResizers();bindLanguageToggle();
Object.assign(window,{OPEN_VIEW:openView,OPEN_MODULE:renderModuleDetail,OPEN_DASHBOARD:openDashboardDetail,OPEN_DASHBOARD_TAB:openDashboardTab,OPEN_PROJECT:openProjectDetail,OPEN_DATA_SHELL_PREVIEW:renderDataShellPreview,OPEN_INVESTMENT_SAMPLE:openInvestmentSample,SET_CONTEXT_FORMAT:setContextFormat,SET_CONTEXT_DASHBOARD:setContextDashboard,COPY_CONTEXT:copyContext,EXPORT_CONTEXT:exportContext,WORKSPACE_SEARCH:workspaceSearch});
boot();
