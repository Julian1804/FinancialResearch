import{escapeHtml}from"./components.js";
import{state}from"./state.js";
export function renderDashboardSubnav(){const root=document.getElementById("dashboard-subnav");if(!root)return;root.innerHTML=state.dashboards.map((dashboard)=>`<button class="dashboard-subitem ${dashboard.dashboard_id===state.activeDashboard?"active":""}" data-nav-dashboard="${escapeHtml(dashboard.dashboard_id)}" title="${escapeHtml(dashboard.dashboard_name)}"><span>${escapeHtml(dashboard.dashboard_name)}</span>${dashboard.mutable?'<small>User</small>':'<small>Sample</small>'}</button>`).join("")}
