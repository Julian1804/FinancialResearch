import { failOperationPanel, finishOperationPanel, setResultPanel, startOperationPanel } from "../ai-bridge.js";
import { workspaceApi } from "../api.js";
import { escapeHtml, head } from "../components.js";
import { renderSqlExplorerPage } from "../database-browser.js";
import { lang } from "../i18n.js";

let updateState = { status: "idle", startedAt: "", elapsedMs: 0, result: null };

const COPY = {
  zh: {
    kicker: "\u6570\u636e\u8fde\u63a5",
    title: "\u66f4\u65b0\u6570\u636e / \u67e5\u770b\u6570\u636e",
    subtitle: "\u6267\u884c\u53d7\u9650\u7684\u53ef\u4fe1\u6570\u636e\u66f4\u65b0\uff0c\u5e76\u8fdb\u5165\u7edf\u4e00\u7684\u53ea\u8bfb\u6570\u636e\u5e93\u6d4f\u89c8\u5668\u3002",
    update: "\u66f4\u65b0\u6570\u636e",
    view: "\u67e5\u770b\u6570\u636e",
    updateTitle: "\u6570\u636e\u66f4\u65b0",
    step: "\u5f53\u524d\u6b65\u9aa4",
    started: "\u672c\u6b21\u68c0\u67e5\u5f00\u59cb\u65f6\u95f4",
    finished: "\u672c\u6b21\u68c0\u67e5\u5b8c\u6210\u65f6\u95f4",
    actualUpdateTime: "\u6700\u8fd1\u6210\u529f\u5165\u5e93\u65f6\u95f4",
    latestDataDate: "\u6700\u65b0\u6570\u636e\u65e5\u671f",
    elapsed: "\u8fd0\u884c\u65f6\u95f4",
    result: "\u66f4\u65b0\u7ed3\u679c",
    added: "\u65b0\u589e",
    updated: "\u66f4\u65b0",
    skipped: "\u8df3\u8fc7",
    failed: "\u5931\u8d25",
    idle: "\u672a\u8fd0\u884c",
    running: "\u6b63\u5728\u66f4\u65b0\u6570\u636e",
    complete: "\u66f4\u65b0\u5b8c\u6210",
    partial: "\u90e8\u5206\u66f4\u65b0\u5b8c\u6210",
    notExecuted: "\u66f4\u65b0\u672a\u6267\u884c",
    failedReason: "\u5931\u8d25\u539f\u56e0",
    canResume: "\u53ef\u7ee7\u7eed\u66f4\u65b0",
    advanced: "\u9ad8\u7ea7\u8bca\u65ad",
    none: "\u65e0",
  },
  en: {
    kicker: "Data Connections",
    title: "Update Data / View Data",
    subtitle: "Run a capped trusted data update or enter the shared read-only Database browser.",
    update: "Update Data",
    view: "View Data",
    updateTitle: "Data Update",
    step: "Current Step",
    started: "Operation Start Time",
    finished: "Operation Finish Time",
    actualUpdateTime: "Latest Successful Materialization Time",
    latestDataDate: "Latest Data Date",
    elapsed: "Runtime",
    result: "Update Result",
    added: "Added",
    updated: "Updated",
    skipped: "Skipped",
    failed: "Failed",
    idle: "Not run",
    running: "Updating data",
    complete: "Update Complete",
    partial: "Partial Update Complete",
    notExecuted: "Update Not Executed",
    failedReason: "Failure Reason",
    canResume: "Can Continue",
    advanced: "Advanced diagnostics",
    none: "None",
  },
};

const copy = () => COPY[lang()] || COPY.zh;
const value = (input) => escapeHtml(input === undefined || input === null ? "" : String(input));

function safeAdvancedSummary(c) {
  const result = updateState.result || {};
  return `<div class="connections-metrics">
    <span><b>${escapeHtml(c.result)}</b>${value(resultLabel(c, result))}</span>
    <span><b>${escapeHtml(c.added)}</b>${value(result.inserted ?? 0)}</span>
    <span><b>${escapeHtml(c.updated)}</b>${value(result.updated ?? 0)}</span>
    <span><b>${escapeHtml(c.skipped)}</b>${value(result.skipped ?? 0)}</span>
    <span><b>${escapeHtml(c.failed)}</b>${value(result.failed ?? 0)}</span>
  </div>`;
}

function statusLabel(c) {
  if (updateState.status === "running") return c.running;
  if (updateState.status === "complete") return c.complete;
  if (updateState.status === "partial") return c.partial;
  if (updateState.status === "not_executed") return c.notExecuted;
  return c.idle;
}

function resultLabel(c, result) {
  if (result?.user_status_zh || result?.user_status_en) return lang() === "en" ? result.user_status_en : result.user_status_zh;
  if (updateState.status === "partial" || result?.status === "partial_update_completed") return c.partial;
  if (updateState.status === "complete") return c.complete;
  if (updateState.status === "not_executed" || result?.status === "update_not_executed") return c.notExecuted;
  return c.idle;
}

function userMessage(c, result) {
  return lang() === "en"
    ? (result?.user_message_en || c.notExecuted)
    : (result?.user_message_zh || c.notExecuted);
}

function failureReason(c, result) {
  const reasons = lang() === "en" ? result?.failed_reasons_en : result?.failed_reasons_zh;
  return Array.isArray(reasons) ? reasons.join("; ") : (reasons || "");
}

function metrics(c) {
  const result = updateState.result || {};
  const elapsed = updateState.elapsedMs ? `${Math.round(updateState.elapsedMs / 1000)}s` : "";
  const rows = [
    [c.step, lang() === "en" ? (result.current_step_en || statusLabel(c)) : (result.current_step_zh || statusLabel(c))],
    [c.started, result.operation_started_at || updateState.startedAt],
    [c.finished, result.operation_finished_at || ""],
    [c.actualUpdateTime, result.latest_successful_materialization_time || result.latest_actual_data_update_time || ""],
    [c.latestDataDate, result.latest_data_date || ""],
    [c.elapsed, elapsed],
    [c.result, resultLabel(c, result)],
    [c.added, result.inserted ?? 0],
    [c.updated, result.updated ?? 0],
    [c.skipped, result.skipped ?? 0],
    [c.failed, result.failed ?? 0],
  ];
  const reason = failureReason(c, result);
  if (reason) rows.push([c.failedReason, reason]);
  if (result.can_resume_zh || result.can_resume_en) rows.push([c.canResume, lang() === "en" ? result.can_resume_en : result.can_resume_zh]);
  return `<div class="connections-metrics">${rows.map(([label, metric]) => `<span><b>${escapeHtml(label)}</b>${value(metric)}</span>`).join("")}</div>`;
}

function isUpdateNotExecuted(result) {
  return result?.status === "update_not_executed" || result?.status === "rejected";
}

function isPartialUpdate(result) {
  return result?.status === "partial_update_completed";
}

function resultSummaryHtml(c, result) {
  const message = userMessage(c, result);
  return `<div class="connections-result-summary">
    <p>${escapeHtml(message)}</p>
    <div class="connections-metrics">
      <span><b>${escapeHtml(c.result)}</b>${value(resultLabel(c, result))}</span>
      <span><b>${escapeHtml(c.started)}</b>${value(result.operation_started_at || updateState.startedAt || "")}</span>
      <span><b>${escapeHtml(c.finished)}</b>${value(result.operation_finished_at || "")}</span>
      <span><b>${escapeHtml(c.actualUpdateTime)}</b>${value(result.latest_successful_materialization_time || result.latest_actual_data_update_time || "")}</span>
      <span><b>${escapeHtml(c.latestDataDate)}</b>${value(result.latest_data_date || "")}</span>
      <span><b>${escapeHtml(c.added)}</b>${value(result.inserted ?? 0)}</span>
      <span><b>${escapeHtml(c.updated)}</b>${value(result.updated ?? 0)}</span>
      <span><b>${escapeHtml(c.skipped)}</b>${value(result.skipped ?? 0)}</span>
      <span><b>${escapeHtml(c.failed)}</b>${value(result.failed ?? 0)}</span>
    </div>
  </div>`;
}

function renderBody(c) {
  return `<section class="connections-actions" aria-label="${escapeHtml(c.title)}">
      <button class="btn primary connection-action" data-connection-mode="update" data-run-update>${escapeHtml(c.update)}</button>
      <button class="btn connection-action" data-connection-mode="browser" data-connection-view-data>${escapeHtml(c.view)}</button>
    </section>
    <section class="product-section connection-update-panel">
      <div class="section-head"><div><h2>${escapeHtml(c.updateTitle)}</h2><p>${escapeHtml(c.subtitle)}</p></div></div>
      ${metrics(c)}
      <details data-advanced-diagnostics>
        <summary>${escapeHtml(c.advanced)}</summary>
        <div class="technical-response">${safeAdvancedSummary(c)}</div>
      </details>
    </section>`;
}

function bind() {
  document.querySelector("[data-connection-view-data]")?.addEventListener("click", () => {
    renderSqlExplorerPage();
  });
  document.querySelector("[data-run-update]")?.addEventListener("click", async () => {
    const c = copy();
    const started = performance.now();
    updateState = { status: "running", startedAt: new Date().toISOString(), elapsedMs: 0, result: null };
    renderConnections();
    const handle = startOperationPanel({
      mode: "connections",
      title: c.update,
      status: "running",
      activeStep: "send_request",
      steps: ["send_request", "render_result"],
      payloadSummary: c.updateTitle,
      progressText: c.running,
      summary: c.running,
      statusText: c.running,
    });
    try {
      const result = await workspaceApi.updates.updateData();
      const notExecuted = isUpdateNotExecuted(result);
      const partial = isPartialUpdate(result);
      updateState = {
        status: notExecuted ? "not_executed" : (partial ? "partial" : "complete"),
        startedAt: updateState.startedAt,
        elapsedMs: performance.now() - started,
        result,
      };
      renderConnections();
      finishOperationPanel(handle, {
        status: notExecuted ? "blocked" : "completed",
        html: resultSummaryHtml(c, result),
        resultText: resultLabel(c, result),
        progressText: resultLabel(c, result),
        summary: userMessage(c, result),
        statusText: resultLabel(c, result),
      });
    } catch (error) {
      const result = {
        status: "update_not_executed",
        blocker: "update_request_failed",
        user_message_zh: "\u66f4\u65b0\u8bf7\u6c42\u672a\u6267\u884c\uff1b\u8bf7\u67e5\u770b\u4e0b\u4e00\u6b65\u6267\u884c\u8ba1\u5212\u3002",
        user_message_en: "The update request was not executed; review the next execution plan.",
        inserted: 0,
        updated: 0,
        skipped: 0,
        failed: 0,
      };
      updateState = { status: "not_executed", startedAt: updateState.startedAt, elapsedMs: performance.now() - started, result };
      renderConnections();
      failOperationPanel(handle, {
        status: "blocked",
        resultText: c.notExecuted,
        error: userMessage(c, result),
        summary: userMessage(c, result),
        statusText: c.notExecuted,
      });
    }
  });
}

export function renderConnections() {
  setResultPanel("connections");
  const c = copy();
  document.getElementById("workspace-main").innerHTML = `<div class="page connections">${head(c.kicker, c.title, c.subtitle)}${renderBody(c)}</div>`;
  bind();
}
