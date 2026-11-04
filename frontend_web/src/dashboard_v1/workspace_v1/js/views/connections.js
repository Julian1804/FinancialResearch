import { failOperationPanel, finishOperationPanel, setResultPanel, startOperationPanel } from "../ai-bridge.js";
import { workspaceApi } from "../api.js";
import { escapeHtml, head } from "../components.js";
import { renderSqlExplorerPage } from "../database-browser.js";
import { lang } from "../i18n.js";

let updateState = { status: "idle", startedAt: "", elapsedMs: 0, result: null };
let tokenState = { saving: false, status: null, messageCode: "" };

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
    tokenTitle: "Morningstar \u79c1\u6709\u51ed\u636e",
    tokenField: "\u65b0 Morningstar Token",
    saveToken: "\u4fdd\u5b58\u5e76\u9a8c\u8bc1",
    cancelToken: "\u53d6\u6d88",
    maskedSuffix: "\u5df2\u4fdd\u5b58\u540e\u7f00",
    lastUpdate: "\u6700\u540e\u66f4\u65b0\u65f6\u95f4",
    expiry: "\u5b89\u5168\u89e3\u7801\u8fc7\u671f\u65f6\u95f4",
    validation: "\u6700\u540e\u9a8c\u8bc1\u7ed3\u679c",
    capability: "\u672c\u5730\u9a8c\u8bc1\u80fd\u529b",
    packageVersion: "\u9a8c\u8bc1\u5305\u7248\u672c",
    validationCallable: "\u9a8c\u8bc1\u8def\u7531",
    unconfigured: "\u672a\u914d\u7f6e",
    configured: "\u5df2\u914d\u7f6e",
    expiringSoon: "\u5373\u5c06\u8fc7\u671f",
    expired: "\u5df2\u8fc7\u671f",
    validationFailed: "\u9a8c\u8bc1\u5931\u8d25",
    savingToken: "\u6b63\u5728\u9a8c\u8bc1\u65b0\u7684 Morningstar \u51ed\u636e...",
    savedToken: "Morningstar \u51ed\u636e\u5df2\u66f4\u65b0\u5e76\u901a\u8fc7\u9a8c\u8bc1\u3002",
    invalidToken: "\u65b0\u51ed\u636e\u672a\u901a\u8fc7\u9a8c\u8bc1\uff0c\u539f\u51ed\u636e\u672a\u88ab\u66ff\u6362\u3002",
    dependencyUnavailable: "Morningstar \u672c\u5730\u9a8c\u8bc1\u73af\u5883\u4e0d\u53ef\u7528\uff0c\u539f\u51ed\u636e\u672a\u88ab\u66ff\u6362\u3002",
    unsupportedCallable: "Morningstar \u672c\u5730\u9a8c\u8bc1\u8def\u7531\u4e0d\u53d7\u5f53\u524d\u5305\u652f\u6301\uff0c\u539f\u51ed\u636e\u672a\u88ab\u66ff\u6362\u3002",
    providerFailure: "\u6682\u65f6\u65e0\u6cd5\u8fde\u63a5 Morningstar\u3002\u539f\u51ed\u636e\u672a\u88ab\u66ff\u6362\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002",
    persistenceFailure: "\u65e0\u6cd5\u5b89\u5168\u4fdd\u5b58\u51ed\u636e\u3002\u539f\u914d\u7f6e\u4fdd\u6301\u4e0d\u53d8\u3002",
    operational: "\u53ef\u7528",
    dependencyUnavailableShort: "\u4f9d\u8d56\u4e0d\u53ef\u7528",
    unsupportedCallableShort: "\u8def\u7531\u4e0d\u652f\u6301",
    providerFailureShort: "\u63d0\u4f9b\u65b9\u4e0d\u53ef\u7528",
    validatedValue: "\u5df2\u9a8c\u8bc1",
    invalidValue: "\u65e0\u6548",
    expiredValue: "\u5df2\u8fc7\u671f",
    providerTimeoutValue: "\u63d0\u4f9b\u65b9\u8d85\u65f6",
    noneValue: "\u65e0",
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
    tokenTitle: "Morningstar Private Credential",
    tokenField: "New Morningstar Token",
    saveToken: "Save and validate",
    cancelToken: "Cancel",
    maskedSuffix: "Saved suffix",
    lastUpdate: "Last update time",
    expiry: "Safely decoded expiry",
    validation: "Last validation result",
    capability: "Local validation capability",
    packageVersion: "Validation package version",
    validationCallable: "Validation route",
    unconfigured: "Not configured",
    configured: "Configured",
    expiringSoon: "Expiring soon",
    expired: "Expired",
    validationFailed: "Validation failed",
    savingToken: "Validating the new Morningstar credential...",
    savedToken: "Morningstar credential was updated and validated.",
    invalidToken: "The new credential did not validate; the original credential was not replaced.",
    dependencyUnavailable: "The local Morningstar validation environment is unavailable. The original credential was not replaced.",
    unsupportedCallable: "The installed Morningstar package does not support the selected validation route. The original credential was not replaced.",
    providerFailure: "Morningstar is temporarily unreachable. The original credential was not replaced; try again later.",
    persistenceFailure: "The credential could not be saved safely. Existing configuration is unchanged.",
    operational: "Operational",
    dependencyUnavailableShort: "Dependency unavailable",
    unsupportedCallableShort: "Unsupported route",
    providerFailureShort: "Provider unavailable",
    validatedValue: "Validated",
    invalidValue: "Invalid",
    expiredValue: "Expired",
    providerTimeoutValue: "Provider timeout",
    noneValue: "None",
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
    ${renderTokenPanel(c)}
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
  document.querySelector("[data-token-cancel]")?.addEventListener("click", () => {
    const input = document.querySelector("[data-token-input]");
    if (input) input.value = "";
    tokenState.messageCode = "";
    renderConnections();
  });
  document.querySelector("[data-token-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const c = copy();
    const input = document.querySelector("[data-token-input]");
    const token = (input?.value || "").trim();
    if (!token || tokenState.saving) return;
    tokenState = { ...tokenState, saving: true, messageCode: "saving" };
    renderConnections();
    try {
      await workspaceApi.connections.updateToken({ md_auth_token: token });
      if (input) input.value = "";
      tokenState = { saving: false, status: await workspaceApi.connections.tokenStatus(), messageCode: "saved" };
    } catch (error) {
      if (input) input.value = "";
      const text = String(error?.message || "");
      let messageCode = "invalid";
      if (text.includes("dependency_unavailable")) messageCode = "dependency";
      else if (text.includes("unsupported_callable")) messageCode = "unsupported";
      else if (text.includes("provider_failure")) messageCode = "provider";
      else if (text.includes("persistence_failure")) messageCode = "persistence";
      tokenState = { saving: false, status: await safeTokenStatus(), messageCode };
    }
    renderConnections();
  });
}

function tokenLabel(c, status) {
  if (!status?.configured) return c.unconfigured;
  if (status.status === "validation_failed") return c.validationFailed;
  if (status.status === "expired") return c.expired;
  if (status.status === "expiring_soon") return c.expiringSoon;
  return c.configured;
}

function localizedValidation(c, status) {
  const value = status?.last_validation_status || "";
  const labels = {
    validated: c.validatedValue,
    invalid_token: c.invalidValue,
    expired_token: c.expiredValue,
    provider_timeout: c.providerTimeoutValue,
    provider_failure: c.providerFailureShort,
    dependency_unavailable: c.dependencyUnavailableShort,
    unsupported_callable: c.unsupportedCallableShort,
  };
  return labels[value] || value || c.none;
}

function capabilityLabel(c, capability) {
  if (!capability) return c.none;
  if (capability.operational) return c.operational;
  if (capability.status === "unsupported_callable") return c.unsupportedCallableShort;
  if (capability.status === "provider_failure") return c.providerFailureShort;
  return c.dependencyUnavailableShort;
}

function tokenMessage(c) {
  const messages = {
    saving: c.savingToken,
    saved: c.savedToken,
    invalid: c.invalidToken,
    dependency: c.dependencyUnavailable,
    unsupported: c.unsupportedCallable,
    provider: c.providerFailure,
    persistence: c.persistenceFailure,
  };
  return messages[tokenState.messageCode] || "";
}

function renderTokenPanel(c) {
  const status = tokenState.status || {};
  const capability = status.credential_capability || {};
  const label = tokenLabel(c, status);
  const cls = status.status === "validation_failed" || status.status === "expired" ? "error" : status.status === "expiring_soon" || !status.configured ? "warning" : "ok";
  return `<section class="product-section morningstar-token-panel" data-morningstar-token-panel>
    <div class="section-head"><div><h2>${escapeHtml(c.tokenTitle)}</h2></div><span class="chip ${cls}">${escapeHtml(label)}</span></div>
    <div class="card token-card">
      <div class="token-status">
        <span><b>${escapeHtml(c.maskedSuffix)}</b><br>${escapeHtml(status.masked_token || c.none)}</span>
        <span><b>${escapeHtml(c.lastUpdate)}</b><br>${escapeHtml(status.last_update_time || c.none)}</span>
        <span><b>${escapeHtml(c.expiry)}</b><br>${escapeHtml(status.jwt_expires_at || status.estimated_expires_at || c.none)}</span>
        <span><b>${escapeHtml(c.validation)}</b><br>${escapeHtml(localizedValidation(c, status))}</span>
        <span><b>${escapeHtml(c.capability)}</b><br>${escapeHtml(capabilityLabel(c, capability))}</span>
        <span><b>${escapeHtml(c.packageVersion)}</b><br>${escapeHtml(capability.package_version || c.none)}</span>
        <span><b>${escapeHtml(c.validationCallable)}</b><br>${escapeHtml(capability.validation_callable || c.none)}</span>
      </div>
      <form data-token-form autocomplete="off">
        <label>${escapeHtml(c.tokenField)}<input data-token-input type="password" autocomplete="new-password" ${tokenState.saving ? "disabled" : ""}></label>
        <div class="actions">
          <button class="btn primary" type="submit" ${tokenState.saving ? "disabled" : ""}>${escapeHtml(c.saveToken)}</button>
          <button class="btn" type="button" data-token-cancel ${tokenState.saving ? "disabled" : ""}>${escapeHtml(c.cancelToken)}</button>
        </div>
      </form>
      <div class="refresh-status" aria-live="polite">${escapeHtml(tokenMessage(c))}</div>
    </div>
  </section>`;
}

async function safeTokenStatus() {
  try { return await workspaceApi.connections.tokenStatus(); }
  catch (error) { return tokenState.status || null; }
}

export function renderConnections() {
  setResultPanel("connections");
  const c = copy();
  document.getElementById("workspace-main").innerHTML = `<div class="page connections">${head(c.kicker, c.title, c.subtitle)}${renderBody(c)}</div>`;
  bind();
  if (!tokenState.status && !tokenState.saving) {
    workspaceApi.connections.tokenStatus().then((status) => {
      tokenState.status = status;
      renderConnections();
    }).catch(() => {});
  }
}
