/** Statistical Analysis View — Research Workspace UI MVP V1 */
import { escapeHtml } from "../components.js";

export async function renderStatisticalAnalysis() {
  const main = document.getElementById("workspace-main");

  let config = {};
  try {
    config = await fetch("/api/research-workspace/status").then(r => r.json()).then(d => d.statistical_analysis_config || {});
  } catch (e) { /* use defaults */ }

  const models = config.model_families || [];
  const datasets = config.datasets || [];
  const warnings = config.warnings || [];
  const freqs = config.frequencies || ["daily", "weekly", "monthly"];

  main.innerHTML = `<div class="page statistical-analysis">
    <div class="card">
      <h3>Statistical Analysis</h3>
      <p class="note">Workflow-oriented analysis configuration. Models labeled "placeholder" return not_implemented.</p>
    </div>

    <!-- Step 1: Project Identity -->
    <div class="card">
      <h4>Step 1 — Analysis Identity</h4>
      <div class="form-row">
        <label>Analysis Name <input type="text" id="sa-name" placeholder="My Analysis" class="input"></label>
        <label>Description <input type="text" id="sa-desc" placeholder="Optional description" class="input"></label>
        <label><input type="checkbox" id="sa-template"> Save as template</label>
      </div>
    </div>

    <!-- Step 2: Model Family -->
    <div class="card">
      <h4>Step 2 — Model Family</h4>
      <select id="sa-model" class="input" style="width:100%">
        ${models.map(m => `<option value="${m.id}" ${!m.executable?'disabled':''}>${escapeHtml(m.name)}${m.executable?'':' (placeholder)'}</option>`).join('')}
      </select>
    </div>

    <!-- Step 3: Dataset -->
    <div class="card">
      <h4>Step 3 — Dataset / Universe</h4>
      <select id="sa-dataset" class="input" style="width:100%">
        ${(datasets||[]).map(d => `<option value="${d.id}">${escapeHtml(d.name)} — ${d.rows} rows, ${d.market}</option>`).join('')}
      </select>
    </div>

    <!-- Step 4-5: Variables -->
    <div class="card">
      <h4>Step 4-5 — Variables</h4>
      <div class="form-row">
        <label>Dependent Variable <select id="sa-depvar" class="input"><option value="">— Select —</option><option value="stock_return_1d">Individual stock daily return</option></select></label>
        <label>Independent Variables <select id="sa-indvars" class="input" multiple style="height:80px"><option value="stock_log_return_1d">Individual stock daily log return</option><option value="stock_turnover_rate">Individual stock turnover rate</option><option value="stock_log_market_cap">Individual stock log market capitalization</option></select></label>
      </div>
    </div>

    <!-- Step 6: Date Range -->
    <div class="card">
      <h4>Step 6 — Date Range & Frequency</h4>
      <div class="form-row">
        <label>Start <input type="date" id="sa-start" value="2025-06-01" class="input"></label>
        <label>End <input type="date" id="sa-end" value="2025-06-16" class="input"></label>
        <label>Frequency <select id="sa-freq" class="input">${freqs.map(f => `<option>${f}</option>`).join('')}</select></label>
      </div>
    </div>

    <!-- Step 7: Preprocessing -->
    <div class="card">
      <h4>Step 7 — Preprocessing</h4>
      <div class="form-row">
        <label>Missing Data <select id="sa-missing" class="input"><option>drop</option><option>keep_flagged</option></select></label>
        <label>Winsorization <select id="sa-winsor" class="input"><option>none</option><option>1%</option><option>5%</option></select></label>
        <label>Standardization <select id="sa-scale" class="input"><option>none</option><option>z_score</option><option>rank_normalize</option></select></label>
        <label><input type="checkbox" id="sa-log"> Log transform</label>
        <label><input type="checkbox" id="sa-diff"> Difference / pct change</label>
        <label><input type="checkbox" id="sa-proxy"> Include proxy fields</label>
        <label><input type="checkbox" id="sa-strict"> Require publication timing evidence</label>
      </div>
    </div>

    <!-- Step 8: Rolling/Window -->
    <div class="card">
      <h4>Step 8 — Rolling / Window Options</h4>
      <div class="form-row">
        <label><input type="checkbox" id="sa-rolling"> Rolling window</label>
        <label>Window size <input type="number" id="sa-window" value="20" min="5" max="60" class="input" style="width:80px"></label>
        <label>Step <input type="number" id="sa-step" value="1" min="1" class="input" style="width:60px"></label>
        <label>Min obs <input type="number" id="sa-minobs" value="10" min="5" class="input" style="width:60px"></label>
      </div>
    </div>

    <!-- Step 9: Diagnostics -->
    <div class="card">
      <h4>Step 9 — Diagnostics / Outputs</h4>
      <div class="form-row">
        <label><input type="checkbox" checked> Summary statistics</label>
        <label><input type="checkbox" checked> Correlation matrix</label>
        <label><input type="checkbox" checked> Coefficient table</label>
        <label><input type="checkbox"> Residual diagnostics</label>
        <label><input type="checkbox"> Missingness report</label>
        <label><input type="checkbox"> Coverage report</label>
        <label><input type="checkbox"> VIF / multicollinearity</label>
      </div>
    </div>

    <!-- Warnings -->
    ${warnings.length ? `<div class="card warning-card"><h4>Warnings</h4><ul>${warnings.map(w=>`<li>${escapeHtml(w)}</li>`).join('')}</ul></div>` : ''}

    <!-- Run + Output -->
    <div class="card">
      <h4>Step 10 — Run Analysis</h4>
      <button class="btn primary" id="sa-run" style="font-size:1.1em;padding:12px 24px">Run Analysis</button>
      <span class="note" style="margin-left:12px">Configuration will be submitted. Backend response determines execution vs not_implemented.</span>
      <div id="sa-output" style="margin-top:16px"></div>
    </div>
  </div>`;

  // Wire run button
  document.getElementById("sa-run").addEventListener("click", async () => {
    const out = document.getElementById("sa-output");
    out.innerHTML = `<div class="loading">Running…</div>`;
    try {
      const payload = {
        analysis_name: document.getElementById("sa-name").value || "Untitled",
        model_family: document.getElementById("sa-model").value,
        dataset: document.getElementById("sa-dataset").value,
        depvar: document.getElementById("sa-depvar").value,
        indvars: Array.from(document.getElementById("sa-indvars").selectedOptions).map(o => o.value),
        date_range: { start: document.getElementById("sa-start").value, end: document.getElementById("sa-end").value },
        frequency: document.getElementById("sa-freq").value,
        missing_policy: document.getElementById("sa-missing").value,
        winsorization: document.getElementById("sa-winsor").value,
        standardization: document.getElementById("sa-scale").value,
        log_transform: document.getElementById("sa-log").checked,
        difference: document.getElementById("sa-diff").checked,
        include_proxy: document.getElementById("sa-proxy").checked,
        require_publish_date: document.getElementById("sa-strict").checked,
        rolling_enabled: document.getElementById("sa-rolling").checked,
        window_size: parseInt(document.getElementById("sa-window").value) || 20,
        step_size: parseInt(document.getElementById("sa-step").value) || 1,
        min_observations: parseInt(document.getElementById("sa-minobs").value) || 10,
      };

      const resp = await fetch("/api/research-workspace/statistical-analysis/run", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
      }).then(r => r.json()).catch(() => ({ status: "error", message: "Backend not reachable" }));

      if (resp.status === "not_implemented") {
        out.innerHTML = `<div class="card warning-card">
          <strong>Model not implemented</strong>
          <p>${escapeHtml(resp.message||'')}</p>
          <p>Config saved: <pre>${escapeHtml(JSON.stringify(resp.config||payload, null, 2))}</pre></p>
        </div>`;
      } else if (resp.status === "error") {
        out.innerHTML = `<div class="card error-card"><strong>Error</strong><p>${escapeHtml(resp.message||'')}</p></div>`;
      } else {
        out.innerHTML = `<div class="card ok-card"><strong>Analysis Complete</strong><pre>${escapeHtml(JSON.stringify(resp, null, 2))}</pre></div>`;
      }
    } catch (err) {
      out.innerHTML = `<div class="card error-card"><strong>Error</strong><p>${escapeHtml(err)}</p></div>`;
    }
  });
}
