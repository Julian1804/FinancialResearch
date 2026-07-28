import { escapeHtml, head } from "../components.js";
import { failOperationPanel, finishOperationPanel, setResultPanel, startOperationPanel } from "../ai-bridge.js";
import { lang, tx } from "../i18n.js";

let activeTab = "scenario";
const tabs = [["scenario", "Scenario Setup"], ["agents", "Agent Parameters"], ["events", "Event Shocks"]];
const simState = {
  scenario_name: "资金行为玩具情景",
  market_universe: "toy_neutral_universe",
  start: "2025-06-01",
  end: "2025-06-16",
  random_seed: 42,
  shock_type: "liquidity_change",
  shock_date: "2025-06-10",
  shock_duration_days: 2,
  shock_magnitude: 0.5,
  agents: {
    trend: { enabled: true, count: 10, risk_preference: 2, lookback: 5 },
    mean_reversion: { enabled: true, count: 15, risk_preference: 2, lookback: 5 },
    liquidity_sensitive: { enabled: true, count: 20, risk_preference: 2, lookback: 5 },
  },
};

const L = {
  zh: {
    scenario: "场景设置",
    agents: "智能体参数",
    events: "事件冲击",
    scenarioName: "场景名称",
    marketScope: "市场范围",
    start: "开始",
    end: "结束",
    seed: "随机种子",
    run: "运行模拟",
    type: "类型",
    enabled: "启用",
    count: "数量",
    risk: "风险偏好",
    lookback: "回看窗口",
    shockType: "冲击类型",
    shockDate: "冲击日期",
    duration: "持续天数",
    intensity: "强度",
    warning: "玩具级情景实验，不代表真实市场，不产生预测、交易或投资建议。",
    started: "模拟已启动",
    submit: "提交玩具情景",
    wait: "等待后端玩具模拟",
    render: "渲染模拟结果",
    completed: "模拟完成",
    failed: "模拟未完成",
    payloadTarget: "玩具模拟参数",
    result: "模拟结果",
    capital: "资金路径",
    price: "资产价格路径",
    behavior: "智能体行为摘要",
    impact: "冲击影响",
    charts: "图表",
    log: "运行日志",
    noRows: "模拟端点未返回步骤行。",
    noPrice: "玩具端点未返回校准后的价格路径；不显示伪造图表。",
  },
  en: {
    scenario: "Scenario setup",
    agents: "Agent parameters",
    events: "Event shock",
    scenarioName: "Scenario name",
    marketScope: "Market scope",
    start: "Start",
    end: "End",
    seed: "Random seed",
    run: "Run simulation",
    type: "Type",
    enabled: "Enabled",
    count: "Count",
    risk: "Risk preference",
    lookback: "Lookback",
    shockType: "Shock type",
    shockDate: "Shock date",
    duration: "Duration days",
    intensity: "Intensity",
    warning: "This simulation is for mechanism testing only and does not represent real markets.",
    started: "Simulation started",
    submit: "Submit simplified simulation",
    wait: "Wait for simulation result",
    render: "Render simulation result",
    completed: "Simulation completed",
    failed: "Simulation did not finish",
    payloadTarget: "Run parameters",
    result: "Simulation result",
    capital: "Capital path",
    price: "Asset-price path",
    behavior: "Agent behavior summary",
    impact: "Shock impact",
    charts: "Charts",
    log: "Run log",
    noRows: "Simulation endpoint did not return step rows.",
    noPrice: "The toy endpoint did not return a calibrated price path; no chart is fabricated.",
  },
};

function local() {
  return L[lang()] || L.zh;
}

function table(headers, rows) {
  return `<table class="table"><thead><tr>${headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function marketLabel(value) {
  if (lang() === "en") return ({ toy_neutral_universe: "Toy neutral universe", "A-share sample": "A-share toy sample", "ETF sample": "ETF toy sample" })[value] || value;
  return ({ toy_neutral_universe: "玩具中性样本", "A-share sample": "A股玩具样本", "ETF sample": "ETF玩具样本" })[value] || value;
}

function shockLabel(value) {
  if (lang() === "en") return String(value || "").replace(/_/g, " ");
  return ({ liquidity_change: "流动性变化", sector_rotation: "行业轮动", policy_event: "政策事件" })[value] || value;
}

function agentLabel(value) {
  if (lang() === "en") return value;
  return ({ trend: "趋势型", mean_reversion: "均值回归型", liquidity_sensitive: "流动性敏感型" })[value] || value;
}

function renderTabs() {
  const ui = local();
  const names = { scenario: ui.scenario, agents: ui.agents, events: ui.events };
  return `<div class="tabs simulation-tabs">${tabs.map(([id]) => `<button class="btn tab ${activeTab === id ? "active" : ""}" data-sim-tab="${id}">${escapeHtml(names[id])}</button>`).join("")}</div>`;
}

function scenarioTab() {
  const ui = local();
  return `<section class="card"><h3>${escapeHtml(ui.scenario)}</h3>
    <div class="form-row">
      <label>${escapeHtml(ui.scenarioName)} <input class="input" id="sim-name" value="${escapeHtml(simState.scenario_name)}"></label>
      <label>${escapeHtml(ui.marketScope)} <select class="input" id="sim-market"><option value="toy_neutral_universe" ${simState.market_universe === "toy_neutral_universe" ? "selected" : ""}>${escapeHtml(marketLabel("toy_neutral_universe"))}</option><option value="A-share sample" ${simState.market_universe === "A-share sample" ? "selected" : ""}>${escapeHtml(marketLabel("A-share sample"))}</option><option value="ETF sample" ${simState.market_universe === "ETF sample" ? "selected" : ""}>${escapeHtml(marketLabel("ETF sample"))}</option></select></label>
    </div>
    <div class="form-row">
      <label>${escapeHtml(ui.start)} <input class="input" type="date" id="sim-start" value="${escapeHtml(simState.start)}"></label>
      <label>${escapeHtml(ui.end)} <input class="input" type="date" id="sim-end" value="${escapeHtml(simState.end)}"></label>
      <label>${escapeHtml(ui.seed)} <input class="input" type="number" id="sim-seed" value="${escapeHtml(simState.random_seed)}"></label>
    </div>
    <div class="actions"><button class="btn primary" id="sim-run">${escapeHtml(ui.run)}</button></div>
  </section>`;
}

function agentsTab() {
  const ui = local();
  return `<section class="card"><h3>${escapeHtml(ui.agents)}</h3>${table([ui.type, ui.enabled, ui.count, ui.risk, ui.lookback], ["trend", "mean_reversion", "liquidity_sensitive"].map((name) => {
    const agent = simState.agents[name];
    return [escapeHtml(agentLabel(name)), `<input type="checkbox" data-agent-enabled="${escapeHtml(name)}" ${agent.enabled ? "checked" : ""}>`, `<input class="input compact-number" data-agent-count="${escapeHtml(name)}" type="number" value="${escapeHtml(agent.count)}">`, `<input class="input compact-number" data-agent-risk="${escapeHtml(name)}" type="number" value="${escapeHtml(agent.risk_preference)}">`, `<input class="input compact-number" data-agent-lookback="${escapeHtml(name)}" type="number" value="${escapeHtml(agent.lookback)}">`];
  }))}<div class="actions"><button class="btn primary" id="sim-run">${escapeHtml(ui.run)}</button></div></section>`;
}

function eventsTab() {
  const ui = local();
  return `<section class="card"><h3>${escapeHtml(ui.events)}</h3>
    <div class="form-row">
      <label>${escapeHtml(ui.shockType)} <select class="input" id="sim-shock-type"><option value="liquidity_change" ${simState.shock_type === "liquidity_change" ? "selected" : ""}>${escapeHtml(shockLabel("liquidity_change"))}</option><option value="sector_rotation" ${simState.shock_type === "sector_rotation" ? "selected" : ""}>${escapeHtml(shockLabel("sector_rotation"))}</option><option value="policy_event" ${simState.shock_type === "policy_event" ? "selected" : ""}>${escapeHtml(shockLabel("policy_event"))}</option></select></label>
      <label>${escapeHtml(ui.shockDate)} <input class="input" type="date" id="sim-shock-date" value="${escapeHtml(simState.shock_date)}"></label>
      <label>${escapeHtml(ui.duration)} <input class="input compact-number" id="sim-shock-duration" type="number" value="${escapeHtml(simState.shock_duration_days)}"></label>
      <label>${escapeHtml(ui.intensity)} <input class="input compact-number" id="sim-shock-intensity" type="number" value="${escapeHtml(simState.shock_magnitude)}" step="0.1"></label>
    </div>
    <div class="actions"><button class="btn primary" id="sim-run">${escapeHtml(ui.run)}</button></div>
  </section>`;
}

function activePanel() {
  if (activeTab === "agents") return agentsTab();
  if (activeTab === "events") return eventsTab();
  return scenarioTab();
}

function numberValue(selector, fallback) {
  const value = Number(document.querySelector(selector)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function saveVisibleSimulationState() {
  simState.scenario_name = document.getElementById("sim-name")?.value || simState.scenario_name;
  simState.market_universe = document.getElementById("sim-market")?.value || simState.market_universe;
  simState.start = document.getElementById("sim-start")?.value || simState.start;
  simState.end = document.getElementById("sim-end")?.value || simState.end;
  simState.random_seed = numberValue("#sim-seed", simState.random_seed);
  simState.shock_type = document.getElementById("sim-shock-type")?.value || simState.shock_type;
  simState.shock_date = document.getElementById("sim-shock-date")?.value || simState.shock_date;
  simState.shock_duration_days = numberValue("#sim-shock-duration", simState.shock_duration_days);
  simState.shock_magnitude = numberValue("#sim-shock-intensity", simState.shock_magnitude);
  Object.keys(simState.agents).forEach((name) => {
    const enabled = document.querySelector(`[data-agent-enabled="${name}"]`);
    simState.agents[name].enabled = enabled ? enabled.checked : simState.agents[name].enabled;
    simState.agents[name].count = numberValue(`[data-agent-count="${name}"]`, simState.agents[name].count);
    simState.agents[name].risk_preference = numberValue(`[data-agent-risk="${name}"]`, simState.agents[name].risk_preference);
    simState.agents[name].lookback = numberValue(`[data-agent-lookback="${name}"]`, simState.agents[name].lookback);
  });
}

function simulationPayload() {
  saveVisibleSimulationState();
  const agents = ["trend", "mean_reversion", "liquidity_sensitive"].map((name) => ({
    type: name,
    enabled: simState.agents[name].enabled,
    count: simState.agents[name].count,
    risk_preference: simState.agents[name].risk_preference,
    lookback: simState.agents[name].lookback,
  }));
  return {
    scenario_name: simState.scenario_name,
    market_universe: simState.market_universe,
    date_range: {
      start: simState.start,
      end: simState.end,
    },
    random_seed: simState.random_seed,
    horizon_days: 10,
    shock: {
      type: simState.shock_type,
      date: simState.shock_date,
      duration_days: simState.shock_duration_days,
      magnitude: simState.shock_magnitude,
    },
    agents,
    toy_only: true,
    no_predictive_claim: true,
    no_investment_advice: true,
  };
}

function simulationResult(resp = {}, request = {}) {
  const ui = local();
  const zh = lang() !== "en";
  const steps = resp.steps || [];
  const totalFlow = steps.reduce((sum, step) => sum + Number(step.flow || 0), 0);
  const rows = steps.slice(0, 8).map((step) => [escapeHtml(step.step ?? ""), escapeHtml(agentLabel(step.agent || "")), escapeHtml(step.flow ?? ""), escapeHtml(shockLabel(step.event || ""))]);
  return `<section>
    <div class="result-tabs">
      <section><h4>${escapeHtml(ui.result)}</h4><div class="catalog-fields">
        <span><b>${escapeHtml(zh ? "运行状态" : "Run status")}</b>${escapeHtml(resp.status ? (zh ? "已返回" : resp.status) : (zh ? "玩具端点已返回" : "returned by toy endpoint"))}</span>
        <span><b>${escapeHtml(zh ? "模拟步骤" : "Simulation steps")}</b>${escapeHtml(steps.length || resp.step_count || 0)}</span>
        <span><b>${escapeHtml(zh ? "智能体数量" : "Agent count")}</b>${escapeHtml(resp.agent_count || request.agents?.reduce((sum, row) => sum + Number(row.enabled ? row.count : 0), 0) || 0)}</span>
        <span><b>${escapeHtml(zh ? "总流量变化" : "Total flow change")}</b>${escapeHtml(totalFlow.toFixed(2))}</span>
        <span><b>${escapeHtml(zh ? "玩具智能体" : "Toy agents")}</b>${escapeHtml((request.agents || []).filter((row) => row.enabled).map((row) => `${agentLabel(row.type)}:${row.count}`).join(", "))}</span>
      </div></section>
      <section><h4>${escapeHtml(ui.capital)}</h4>${rows.length ? table([zh ? "步骤" : "Step", zh ? "智能体" : "Agent", zh ? "流量变化" : "Flow change", zh ? "事件" : "Event"], rows) : `<div class="result-blocker">${escapeHtml(ui.noRows)}</div>`}</section>
      <section><h4>${escapeHtml(ui.price)}</h4><div class="result-blocker">${escapeHtml(ui.noPrice)}</div></section>
      <section><h4>${escapeHtml(ui.behavior)}</h4><p>${escapeHtml(ui.warning)}</p></section>
      <section><h4>${escapeHtml(ui.impact)}</h4><p>${escapeHtml(shockLabel(request.shock?.type || ""))}: ${escapeHtml(request.shock?.date || "")}, ${escapeHtml(request.shock?.magnitude ?? "")}</p></section>
      <section><h4>${escapeHtml(ui.charts)}</h4><div class="result-blocker">${escapeHtml(ui.noPrice)}</div></section>
      <section><h4>${escapeHtml(ui.log)}</h4><p>${escapeHtml(zh ? "未写入生产库。已使用可见表单参数。" : "No production database write. Payload used visible form values.")}</p></section>
    </div>
  </section>`;
}

function bindSimulation() {
  document.querySelectorAll("input, select").forEach((input) => input.addEventListener("change", saveVisibleSimulationState));
  document.querySelectorAll("[data-sim-tab]").forEach((button) => button.addEventListener("click", () => { saveVisibleSimulationState(); activeTab = button.dataset.simTab; renderAgentSimulation(); }));
  document.getElementById("sim-run")?.addEventListener("click", async () => {
    const button = document.getElementById("sim-run");
    if (button) button.disabled = true;
    const ui = local();
    const payload = simulationPayload();
    const handle = startOperationPanel({
      mode: "agent_simulation",
      title: ui.started,
      status: ui.started,
      activeStep: "submit_simulation",
      steps: ["submit_simulation", "wait_simulation", "render_result"],
      payloadSummary: `${ui.payloadTarget}: ${payload.scenario_name} / ${marketLabel(payload.market_universe)}`,
      progressText: `${ui.payloadTarget}: ${payload.scenario_name} / ${marketLabel(payload.market_universe)}`,
    });
    try {
      const resp = await fetch("/api/research-workspace/agent-simulation/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then((r) => r.json());
      finishOperationPanel(handle, { status: ui.completed, html: simulationResult(resp, payload), resultText: ui.completed });
    } catch (error) {
      failOperationPanel(handle, { status: ui.failed, errorHtml: `<div class="result-blocker">${escapeHtml(error.message || error)}</div>` });
    } finally {
      if (button) button.disabled = false;
    }
  });
}

export async function renderAgentSimulation() {
  setResultPanel("agent_simulation");
  const labels = tx("simulation");
  const ui = local();
  document.getElementById("workspace-main").innerHTML = `<div class="page agent-simulation">
    ${head(labels.kicker, labels.title, labels.subtitle)}
    <p class="warning-text">${escapeHtml(ui.warning)}</p>
    ${renderTabs()}
    ${activePanel()}
  </div>`;
  bindSimulation();
}
