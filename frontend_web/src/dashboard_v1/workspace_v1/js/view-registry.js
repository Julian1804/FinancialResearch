import {renderApps} from"./views/apps.js";
import {renderConnections}from"./views/connections.js";
import {renderDataShellPreview}from"./views/data-shell-preview.js";
import {renderDashboards}from"./views/dashboards.js";
import {renderLegacy}from"./views/legacy.js";
import {renderModules}from"./views/modules.js";
import {renderOverview}from"./views/overview.js";
import {renderProjects}from"./views/projects.js";
import {renderDatabaseStatus}from"./views/database-status.js";
import {renderStatisticalAnalysis}from"./views/statistical-analysis.js";
import {renderAgentSimulation}from"./views/agent-simulation.js";
import {renderModelingWorkbench}from"./views/modeling-workbench.js";
export const viewRegistry=[
  {view_id:"overview",label:"Overview",route:"overview",view_module:"overview.js",nav_group:"workspace",enabled:true,requires_app:false,requires_dashboard:false,requires_module:false,render:renderOverview},
  {view_id:"database_status",label:"Database",route:"database_status",view_module:"database-status.js",nav_group:"research",enabled:true,requires_app:false,requires_dashboard:false,requires_module:false,render:renderDatabaseStatus},
  {view_id:"statistical_analysis",label:"Statistical Analysis",route:"statistical_analysis",view_module:"statistical-analysis.js",nav_group:"internal",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderStatisticalAnalysis},
  {view_id:"modeling_workbench",label:"Modeling Workbench",route:"modeling_workbench",view_module:"modeling-workbench.js",nav_group:"research",enabled:true,requires_app:false,requires_dashboard:false,requires_module:false,render:renderModelingWorkbench},
  {view_id:"agent_simulation",label:"Agent Simulation",route:"agent_simulation",view_module:"agent-simulation.js",nav_group:"research",enabled:true,requires_app:false,requires_dashboard:false,requires_module:false,render:renderAgentSimulation},
  {view_id:"apps",label:"Apps",route:"apps",view_module:"apps.js",nav_group:"workspace",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderApps},
  {view_id:"projects",label:"Legacy Research Projects",route:"projects",view_module:"projects.js",nav_group:"internal",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderProjects},
  {view_id:"connections",label:"Connections",route:"connections",view_module:"connections.js",nav_group:"workspace",enabled:true,requires_app:false,requires_dashboard:false,requires_module:false,render:renderConnections},
  {view_id:"data_shell_preview",label:"Data Shell Preview",route:"data_shell_preview",view_module:"data-shell-preview.js",nav_group:"internal",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderDataShellPreview},
  {view_id:"modules",label:"Plug-in Library",route:"modules",view_module:"modules.js",nav_group:"library",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderModules},
  {view_id:"dashboards",label:"My Dashboards",route:"dashboards",view_module:"dashboards.js",nav_group:"library",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderDashboards},
  {view_id:"legacy",label:"Legacy",route:"legacy",view_module:"legacy.js",nav_group:"internal",enabled:false,requires_app:false,requires_dashboard:false,requires_module:false,render:renderLegacy},
  {view_id:"module_detail",label:"Plug-in Detail",route:"module_detail",view_module:"module-detail.js",nav_group:"detail",enabled:false,requires_app:false,requires_dashboard:false,requires_module:true},
  {view_id:"dashboard_detail",label:"Dashboard Detail",route:"dashboard_detail",view_module:"dashboard-detail.js",nav_group:"detail",enabled:false,requires_app:false,requires_dashboard:true,requires_module:false}
];
export function resolveView(id){return viewRegistry.find((item)=>item.view_id===id&&item.enabled)}
