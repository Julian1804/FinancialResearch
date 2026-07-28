import { workspaceApi } from "./api.js";
import { escapeHtml } from "./components.js";
import { contextRequest, state } from "./state.js";
import { lang, tx } from "./i18n.js";
import { formatMissingDisplayLabel, formatOperationStatus, formatOperationStep } from "./display-model.js";

export function contextText() {
  if (!state.context) return "";
  return state.contextFormat === "json" ? JSON.stringify(state.context.json || {}, null, 2) : (state.context.markdown || "");
}

let workbenchBridgeState = {};
let workbenchBridgeStatus = "";
const operationTimers = new Map();

function nodes() {
  return {
    root: document.getElementById("ai-bridge"),
    name: document.getElementById("bridge-name"),
    eyebrow: document.querySelector("#ai-bridge .bridge-title .eyebrow"),
    copy: document.querySelector("#ai-bridge>p"),
    module: document.getElementById("bridge-module"),
    status: document.getElementById("bridge-status"),
    preview: document.getElementById("bridge-preview"),
  };
}

function resultConfig(mode) {
  return tx("resultPanel")[mode] || tx("resultPanel").overview;
}

function elapsedText(ms) {
  const total = Math.max(0, Math.floor(Number(ms || 0) / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = String(total % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function operationMode(mode) {
  return mode === "workbench" ? "workbench" : (mode || "overview");
}

function semanticText(payload, key, fallback = "") {
  const text = payload[`${key}Text`];
  const semanticKey = payload[`${key}Key`];
  const raw = payload[key];
  if (text) return text;
  if (semanticKey) return formatOperationStatus(semanticKey, lang());
  if (typeof raw === "string" && /^[a-z][a-z0-9_]*$/.test(raw)) return formatOperationStatus(raw, lang());
  return fallback || raw || formatMissingDisplayLabel(key, lang());
}

function renderOperationHtml(statePayload) {
  const op = tx("operation") || {};
  const steps = statePayload.steps || [];
  const activeStep = statePayload.activeStep || steps[0] || "render_result";
  const startedAt = statePayload.startedAt || Date.now();
  const elapsedMs = statePayload.elapsedMs ?? (Date.now() - startedAt);
  const fields = [
    [op.status || "Status", semanticText(statePayload, "status", formatOperationStatus("running", lang()))],
    [op.currentStep || "Current step", formatOperationStep(activeStep, lang())],
    [op.started || "Started", new Date(startedAt).toLocaleTimeString()],
    [op.elapsed || "Elapsed", elapsedText(elapsedMs)],
    [op.target || "Target", semanticText(statePayload, "payloadSummary", semanticText(statePayload, "target", semanticText(statePayload, "title")))],
    [op.resultBlocker || "Result / reason unavailable", semanticText(statePayload, "result", statePayload.resultText || formatOperationStatus(statePayload.failed ? "blocked" : "pending", lang()))],
  ];
  const stepHtml = steps.length
    ? `<ol class="operation-steps">${steps.map((step) => `<li class="${step === activeStep ? "active" : ""}">${escapeHtml(formatOperationStep(step, lang()))}</li>`).join("")}</ol>`
    : "";
  return `<section class="operation-lifecycle" data-operation-lifecycle="${escapeHtml(statePayload.mode || "")}">
    <h3>${escapeHtml(semanticText(statePayload, "title", op.status || "Operation"))}</h3>
    <div class="operation-grid">${fields.map(([key, value]) => `<span><b>${escapeHtml(key)}</b>${escapeHtml(value)}</span>`).join("")}</div>
    ${stepHtml}
    ${semanticText(statePayload, "progress", statePayload.progressText) ? `<p class="operation-progress">${escapeHtml(semanticText(statePayload, "progress", statePayload.progressText))}</p>` : ""}
    ${statePayload.html || ""}
  </section>`;
}

function applyOperationPanel(statePayload, resultHtmlByTab = null, activeTab = null) {
  const mode = operationMode(statePayload.mode);
  const html = renderOperationHtml(statePayload);
  if (mode === "workbench") {
    const labels = tx("workbench");
    const tab = activeTab || statePayload.tab || labels.tabs[0];
    const tabPayload = resultHtmlByTab || { [tab]: html };
    setWorkbenchBridge({
      ...tabPayload,
      active: tab,
      status: statePayload.status,
      summary: statePayload.summary,
    });
    return;
  }
  setResultPanel(mode, {
    title: statePayload.panelTitle,
    status: statePayload.status,
    statusText: statePayload.statusText,
    summary: statePayload.summary,
    html,
  });
}

function clearOperationTimer(mode) {
  const timer = operationTimers.get(mode);
  if (timer) clearInterval(timer);
  operationTimers.delete(mode);
}

export function startOperationPanel(payload = {}) {
  const mode = operationMode(payload.mode);
  clearOperationTimer(mode);
  const op = tx("operation") || {};
  const statePayload = {
    ...payload,
    mode,
    startedAt: Date.now(),
    status: payload.statusKey || payload.status || "running",
    progressText: payload.progressText || op.waiting,
  };
  const handle = { mode, startedAt: statePayload.startedAt, statePayload };
  applyOperationPanel(handle.statePayload);
  const timer = setInterval(() => {
    const current = handle.statePayload || statePayload;
    applyOperationPanel({ ...current, elapsedMs: Date.now() - (current.startedAt || handle.startedAt) });
  }, 1000);
  operationTimers.set(mode, timer);
  return handle;
}

export function updateOperationPanel(handle, payload = {}) {
  const base = handle?.statePayload || {};
  const mode = operationMode(payload.mode || handle?.mode || base.mode);
  const next = { ...base, ...payload, mode, startedAt: handle?.startedAt || base.startedAt || Date.now() };
  if (handle) handle.statePayload = next;
  applyOperationPanel(next);
}

export function finishOperationPanel(handle, payload = {}) {
  const op = tx("operation") || {};
  const base = handle?.statePayload || {};
  const mode = operationMode(payload.mode || handle?.mode || base.mode);
  clearOperationTimer(mode);
  const startedAt = handle?.startedAt || base.startedAt || Date.now();
  const next = {
    ...base,
    ...payload,
    mode,
    startedAt,
    elapsedMs: payload.elapsedMs ?? (Date.now() - startedAt),
    status: payload.statusKey || payload.status || "completed",
    resultText: payload.resultText || formatOperationStatus(payload.resultKey || "completed", lang()),
    progressText: payload.progressText || op.rendered,
  };
  applyOperationPanel(next, payload.resultHtmlByTab, payload.activeTab);
}

export function failOperationPanel(handle, payload = {}) {
  const op = tx("operation") || {};
  const base = handle?.statePayload || {};
  const mode = operationMode(payload.mode || handle?.mode || base.mode);
  clearOperationTimer(mode);
  const startedAt = handle?.startedAt || base.startedAt || Date.now();
  const html = payload.errorHtml || `<div class="result-blocker">${escapeHtml(payload.error || op.failed || "")}</div>`;
  const next = {
    ...base,
    ...payload,
    mode,
    startedAt,
    elapsedMs: Date.now() - startedAt,
    failed: true,
    status: payload.statusKey || payload.status || "failed",
    resultText: payload.resultText || formatOperationStatus(payload.resultKey || "blocked", lang()),
    progressText: payload.progressText || op.exactBlocker,
    html,
  };
  applyOperationPanel(next, payload.resultHtmlByTab, payload.activeTab);
}

export function resetBridgeMode() {
  setResultPanel("overview");
}

export function setTaskBridgeMode(mode) {
  setResultPanel(mode);
}

export function setResultPanel(mode, payload = {}) {
  const cfg = resultConfig(mode);
  const n = nodes();
  n.root?.classList.remove("workbench-bridge");
  n.root?.classList.add("task-bridge", "result-bridge");
  if (n.name) n.name.textContent = payload.title || cfg.name;
  if (n.eyebrow) n.eyebrow.textContent = payload.eyebrow || cfg.eyebrow;
  if (n.copy) n.copy.textContent = payload.summary || cfg.empty;
  if (n.module) n.module.textContent = payload.owner || cfg.name;
  if (n.status) n.status.textContent = semanticText(payload, "status", cfg.status);
  if (n.preview) n.preview.innerHTML = payload.html || `<div class="result-empty">${escapeHtml(cfg.empty)}</div>`;
}

function defaultWorkbenchState() {
  const tabs = tx("workbench").tabs;
  return Object.fromEntries(tabs.map((tab) => [tab, `<div class="result-empty">${escapeHtml(resultConfig("workbench").empty)}</div>`]));
}

function renderWorkbenchTabs(active = tx("workbench").tabs[0]) {
  const tabs = tx("workbench").tabs.map((tab) => `<button class="btn result-tab ${tab === active ? "active" : ""}" data-workbench-output-tab="${escapeHtml(tab)}">${escapeHtml(tab)}</button>`).join("");
  const n = nodes();
  if (n.preview) n.preview.innerHTML = `<div class="workbench-output-tabs">${tabs}</div><div class="workbench-output-panel">${workbenchBridgeState[active] || ""}</div>`;
  if (n.status) n.status.textContent = workbenchBridgeStatus || tx("workbench").output;
}

export function setWorkbenchBridge(payload = {}) {
  const cfg = resultConfig("workbench");
  const n = nodes();
  n.root?.classList.remove("task-bridge");
  n.root?.classList.add("workbench-bridge", "result-bridge");
  if (n.name) n.name.textContent = cfg.name;
  if (n.eyebrow) n.eyebrow.textContent = cfg.eyebrow;
  if (n.copy) n.copy.textContent = payload.summary || cfg.empty;
  if (n.module) n.module.textContent = cfg.name;
  workbenchBridgeStatus = semanticText(payload, "status", cfg.status);
  workbenchBridgeState = { ...defaultWorkbenchState(), ...payload };
  renderWorkbenchTabs(payload.active || tx("workbench").tabs[0]);
}

export async function loadContext() {
  const dashboard = state.contextDashboard;
  if (!dashboard) {
    state.context = null;
    return null;
  }
  state.context = await workspaceApi.workspace.contextPack(contextRequest());
  renderContext();
  return state.context;
}

export function renderContext() {
  const preview = document.getElementById("bridge-preview");
  const status = document.getElementById("bridge-status");
  if (!preview || !status) return;
  const text = contextText();
  preview.textContent = text || "Dashboard handoff is available only from dashboard pages.";
  status.textContent = text ? `Dashboard handoff ready: ${text.length} characters.` : "Dashboard handoff not selected.";
}

export function setContextFormat(format) {
  state.contextFormat = format;
  document.getElementById("fmt-markdown")?.classList.toggle("active", format === "markdown");
  document.getElementById("fmt-json")?.classList.toggle("active", format === "json");
  renderContext();
}

export async function setContextDashboard(dashboardId) {
  state.contextDashboard = String(dashboardId || "");
  const select = document.getElementById("bridge-dashboard");
  if (select) select.value = state.contextDashboard;
  return loadContext();
}

export async function copyContext() {
  const text = contextText();
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    document.body.appendChild(box);
    box.select();
    document.execCommand("copy");
    box.remove();
  }
}

export function exportContext() {
  const text = contextText();
  if (!text) return;
  const ext = state.contextFormat === "json" ? "json" : "md";
  const name = `fr_workspace_dashboard_${state.contextDashboard}.${ext}`;
  const anchor = document.createElement("a");
  const url = URL.createObjectURL(new Blob([text], { type: state.contextFormat === "json" ? "application/json" : "text/markdown" }));
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export async function saveHandoffDraft() {
  const text = contextText();
  if (!text) return;
  await workspaceApi.userWorkspace.saveHandoff({ ...contextRequest(), title: `Dashboard Handoff / ${state.contextDashboard}`, body: text });
}

export function populateContextDashboards() {
  const select = document.getElementById("bridge-dashboard");
  if (!select) return;
  const dashboards = [...state.dashboards, ...state.archivedDashboards];
  select.innerHTML = '<option value="">Select a dashboard</option>' + dashboards.map((dashboard) => `<option value="${escapeHtml(dashboard.dashboard_id)}">${escapeHtml(dashboard.dashboard_name)}</option>`).join("");
  select.value = state.contextDashboard;
}

export function bindAiBridge() {
  document.querySelectorAll("[data-context-format]").forEach((button) => button.addEventListener("click", () => setContextFormat(button.dataset.contextFormat)));
  document.getElementById("bridge-dashboard")?.addEventListener("change", (event) => setContextDashboard(event.target.value));
  document.getElementById("bridge-copy")?.addEventListener("click", copyContext);
  document.getElementById("bridge-export")?.addEventListener("click", exportContext);
  document.getElementById("bridge-save-handoff")?.addEventListener("click", saveHandoffDraft);
  document.getElementById("bridge-preview")?.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-workbench-output-tab]");
    if (tab) renderWorkbenchTabs(tab.dataset.workbenchOutputTab);
  });
}
