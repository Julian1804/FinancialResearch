// Presentation helpers for the ordinary Modeling API. Capability and run truth remain server-owned.
export const FAMILY_ORDER = ["regression", "classification", "univariate_forecast", "multivariate_time_series", "panel", "volatility", "regime_state"];

export function effectiveCapability(model, task = "") {
  const mode = model?.task_modes?.[task];
  return mode ? {...model, ...mode} : model;
}

export function compatibleModels(catalog, selected, task = "") {
  const current = effectiveCapability(selected, task);
  if (!current?.comparison_group) return [];
  return catalog.filter(row => row.available && row.model_id !== selected.model_id &&
    effectiveCapability(row, task)?.comparison_group === current.comparison_group &&
    row.input_shape === selected.input_shape);
}

export function seriesKey(input, panelIds = []) {
  if (panelIds.length) return `Equity:Listings:${panelIds.join("|")}:${input.metric}`;
  return `${input.universe}:${input.universe === "Fund" ? "fund_share_class" : "listing"}:${input.id}:${input.metric}`;
}

export function parseParameter(name, raw) {
  const value = String(raw ?? "").trim();
  if (!value) return undefined;
  if (["weights", "sigma", "order", "seasonal_order", "future_exog_contract"].includes(name)) return JSON.parse(value);
  if (["switching_variance", "entity_effects", "time_effects"].includes(name)) return value === "true";
  if (["weights_basis", "sigma_basis", "rank_basis", "trend", "seasonal", "cov_type", "distribution", "mean", "deterministic", "level"].includes(name)) return value;
  const number = Number(value);
  if (!Number.isFinite(number)) throw new Error(`Invalid number for ${name}`);
  return number;
}

export function executionFromDraft(draft, model, catalog) {
  const parameters = Object.fromEntries(Object.entries(draft.parameters || {})
    .map(([name, raw]) => [name, parseParameter(name, raw)]).filter(([, value]) => value !== undefined));
  const operation = draft.operation;
  if (operation === "comparison") {
    const ids = [model.model_id, ...draft.comparisonIds];
    if (ids.length < 2 || draft.comparisonIds.some(id => !compatibleModels(catalog, model, draft.task).some(row => row.model_id === id))) throw new Error("incompatible_comparison");
    const byModel = Object.fromEntries(ids.map(id => [id, id === model.model_id ? parameters : {}]));
    return {operation, model_ids: ids, parameters: byModel};
  }
  if (operation === "optimization") {
    if (!model.supports_tuning) throw new Error("unsupported_optimization");
    const search_space = {};
    for (const [name, raw] of Object.entries(draft.searchSpace || {})) {
      if (!String(raw).trim()) continue;
      if (!model.tunable_parameters.includes(name)) throw new Error("unsupported_optimization");
      const values = String(raw).split(",").map(item => parseParameter(name, item));
      if (values.some(item => item === undefined)) throw new Error("invalid_search_space");
      search_space[name] = values;
    }
    return {operation, model_id: model.model_id, parameters, search_space, budget: Number(draft.budget || 20), seed: Number(draft.seed || 0)};
  }
  return {operation: "run", model_id: model.model_id, parameters};
}

export function previewPayload(draft, model, catalog) {
  const capability = effectiveCapability(model, draft.task);
  if (!model?.available) throw new Error("unavailable_capability");
  if (!draft.start || !draft.end || draft.start > draft.end ||
      (Date.parse(draft.end) - Date.parse(draft.start)) / 86400000 > 366) throw new Error("invalid_date_range");
  const inputs = draft.inputs || [];
  const ys = inputs.filter(item => item.role === "Y");
  const xs = inputs.filter(item => item.role === "X");
  if (!ys.length || (capability.required_inputs.includes("X") && !xs.length)) throw new Error("missing_inputs");
  if (model.input_shape !== "multivariate_time_series" && ys.length !== 1) throw new Error("target_count");
  if (model.input_shape === "multivariate_time_series" && ys.length < 2) throw new Error("target_count");
  if (model.input_shape === "univariate_time_series" && xs.length) throw new Error("unexpected_features");
  if (model.input_shape === "panel" && (draft.panelIds || []).length < 2) throw new Error("panel_entities");
  const variable = (item, index) => ({name: `v${index + 1}`, series_key: seriesKey(item, model.input_shape === "panel" ? draft.panelIds : []),
    role: item.role, transformations: item.transformations || []});
  const all = inputs.map(variable);
  const y = all.filter(item => item.role === "Y"), x = all.filter(item => item.role === "X");
  const execution = executionFromDraft(draft, model, catalog);
  const request = {y, x, start: draft.start, end: draft.end, shape: model.input_shape,
    horizon: Number(draft.horizon || 0), missing_strategy: draft.missing,
    missing_options: draft.missing === "forward_fill" ? {max_age_days: Number(draft.maxAge || 7)} : {},
    split: {kind: "chronological", train_fraction: Number(draft.trainFraction || 0.8)},
    validation: {kind: "holdout"}, alignment: {kind: "exact_economic_time"},
    time_features: draft.timeFeatures || [], frequency: draft.frequency || null,
    label_definition: draft.task === "classification" ? {kind: "binary_threshold", threshold: Number(draft.threshold || 0)} : {},
    model_id: model.model_id, parameters: execution.parameters,
    operation: execution.operation};
  if (execution.operation === "comparison") {
    request.comparison_model_ids = execution.model_ids;
    request.comparison_parameters = execution.parameters;
    request.parameters = {};
  }
  if (execution.operation === "optimization") {
    request.optimization_search_space = execution.search_space;
    request.optimization_budget = execution.budget;
    request.optimization_seed = execution.seed;
  }
  return {request, execution};
}

export function resultKind(run) {
  if (run?.operation === "comparison" || run?.result?.schema_version === "fr_model_comparison_v1" || Array.isArray(run?.result?.models)) return "comparison";
  if (run?.operation === "optimization" || Array.isArray(run?.result?.trials) && run?.result?.final) return "optimization";
  return run?.result?.family_result?.kind || run?.result?.family || "unknown";
}
