"""In-code Stage 1 statistical contracts. No runtime or persisted authority."""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyContract:
    family: str
    input_shape: str
    evaluation_metrics: tuple[str, ...]
    result_kind: str
    comparison_group: str | None


FAMILIES = {
    "regression": FamilyContract("regression", "supervised", ("rmse", "mae", "r2"), "numeric_prediction", "numeric_regression"),
    "classification": FamilyContract("classification", "supervised", ("accuracy", "precision", "recall", "per_class"), "class_label", "classification"),
    "univariate_forecast": FamilyContract("univariate_forecast", "univariate_time_series", ("rmse", "mae", "r2"), "conditional_mean", "univariate_forecast"),
    "multivariate_time_series": FamilyContract("multivariate_time_series", "multivariate_time_series", ("per_target",), "vector_forecast", "vector_forecast"),
    "panel": FamilyContract("panel", "panel", ("rmse", "mae", "r2"), "numeric_prediction", "panel_level"),
    "volatility": FamilyContract("volatility", "univariate_time_series", (), "conditional_volatility", None),
    "regime_state": FamilyContract("regime_state", "univariate_time_series", (), "state_probabilities", None),
}


@dataclass(frozen=True)
class ModelOverride:
    model_id: str
    family: str
    adapter: str
    input_shape: str | None = None
    optional_parameters: tuple[str, ...] = ()
    required_parameters: tuple[str, ...] = ()
    task_parameters: tuple[str, ...] = ()
    tunable_parameters: tuple[str, ...] = ()
    output_kinds: tuple[str, ...] = ()
    metrics: tuple[str, ...] | None = None
    comparison_group: str | None = None
    restriction: str | None = None
    unavailable_reason: str | None = None


MODELS = {
    "ols": ModelOverride("ols", "regression", "native"),
    "wls": ModelOverride("wls", "regression", "statsmodels", required_parameters=("weights", "weights_basis"), restriction="explicit positive training-row weights"),
    "gls": ModelOverride("gls", "regression", "statsmodels", required_parameters=("sigma", "sigma_basis"), restriction="positive-definite training covariance"),
    "ridge": ModelOverride("ridge", "regression", "native", optional_parameters=("alpha",), tunable_parameters=("alpha",)),
    "lasso": ModelOverride("lasso", "regression", "sklearn", optional_parameters=("alpha", "max_iter", "tol"), tunable_parameters=("alpha",)),
    "elastic_net": ModelOverride("elastic_net", "regression", "sklearn", optional_parameters=("alpha", "l1_ratio", "max_iter", "tol"), tunable_parameters=("alpha", "l1_ratio")),
    "logistic_regression": ModelOverride("logistic_regression", "classification", "sklearn", optional_parameters=("max_iter", "tol", "seed"), output_kinds=("positive_class_probability",)),
    "decision_tree": ModelOverride("decision_tree", "regression", "sklearn", optional_parameters=("seed", "max_depth", "min_samples_leaf"), tunable_parameters=("max_depth", "min_samples_leaf"), output_kinds=("numeric_prediction", "class_label")),
    "random_forest": ModelOverride("random_forest", "regression", "sklearn", optional_parameters=("seed", "max_depth", "min_samples_leaf", "n_estimators"), tunable_parameters=("max_depth", "min_samples_leaf", "n_estimators"), output_kinds=("numeric_prediction", "class_label")),
    "extra_trees": ModelOverride("extra_trees", "regression", "sklearn", optional_parameters=("seed", "max_depth", "min_samples_leaf", "n_estimators"), tunable_parameters=("max_depth", "min_samples_leaf", "n_estimators"), output_kinds=("numeric_prediction", "class_label")),
    "gradient_boosting": ModelOverride("gradient_boosting", "regression", "sklearn", optional_parameters=("seed", "max_depth", "min_samples_leaf", "n_estimators"), tunable_parameters=("max_depth", "min_samples_leaf", "n_estimators"), output_kinds=("numeric_prediction", "class_label")),
    "ar": ModelOverride("ar", "univariate_forecast", "statsmodels", optional_parameters=("order",), task_parameters=("forecast_steps",), tunable_parameters=("order",)),
    "ma": ModelOverride("ma", "univariate_forecast", "statsmodels", optional_parameters=("order",), task_parameters=("forecast_steps",), tunable_parameters=("order",)),
    "arma": ModelOverride("arma", "univariate_forecast", "statsmodels", optional_parameters=("order",), task_parameters=("forecast_steps",), tunable_parameters=("order",)),
    "arima": ModelOverride("arima", "univariate_forecast", "statsmodels", optional_parameters=("order",), task_parameters=("forecast_steps",), tunable_parameters=("order",)),
    "sarima": ModelOverride("sarima", "univariate_forecast", "statsmodels", required_parameters=("seasonal_order",), optional_parameters=("order",), task_parameters=("forecast_steps",), tunable_parameters=("order", "seasonal_order")),
    "sarimax": ModelOverride("sarimax", "univariate_forecast", "statsmodels", input_shape="supervised", required_parameters=("seasonal_order", "future_exog_contract"), optional_parameters=("order",), task_parameters=("forecast_steps", "future_exog_contract"), output_kinds=("conditional_scenario_mean",), metrics=(), comparison_group="", restriction="future X is a declared scenario; no observed-history score"),
    "exponential_smoothing": ModelOverride("exponential_smoothing", "univariate_forecast", "statsmodels", task_parameters=("forecast_steps",)),
    "holt": ModelOverride("holt", "univariate_forecast", "statsmodels", task_parameters=("forecast_steps",)),
    "holt_winters": ModelOverride("holt_winters", "univariate_forecast", "statsmodels", required_parameters=("seasonal_periods",), optional_parameters=("trend", "seasonal"), task_parameters=("forecast_steps",)),
    "var": ModelOverride("var", "multivariate_time_series", "statsmodels", optional_parameters=("lags", "trend"), task_parameters=("forecast_steps",)),
    "vecm": ModelOverride("vecm", "multivariate_time_series", "statsmodels", required_parameters=("rank_basis",), optional_parameters=("k_ar_diff", "coint_rank", "deterministic"), task_parameters=("forecast_steps",)),
    "pooled_ols": ModelOverride("pooled_ols", "panel", "linearmodels", optional_parameters=("cov_type",)),
    "fixed_effects": ModelOverride("fixed_effects", "panel", "linearmodels", optional_parameters=("cov_type", "entity_effects", "time_effects"), output_kinds=("numeric_prediction", "fit_only_diagnostic")),
    "random_effects": ModelOverride("random_effects", "panel", "linearmodels", optional_parameters=("cov_type",)),
    "first_difference": ModelOverride("first_difference", "panel", "linearmodels", optional_parameters=("cov_type",), output_kinds=("fit_only_diagnostic",), metrics=(), comparison_group="", restriction="differenced equation; no level forecast"),
    "fama_macbeth": ModelOverride("fama_macbeth", "panel", "linearmodels", optional_parameters=("cov_type",)),
    "arch": ModelOverride("arch", "volatility", "arch", optional_parameters=("mean", "p", "distribution", "simulations", "seed"), task_parameters=("forecast_steps",)),
    "garch": ModelOverride("garch", "volatility", "arch", optional_parameters=("mean", "p", "q", "distribution", "simulations", "seed"), task_parameters=("forecast_steps",)),
    "egarch": ModelOverride("egarch", "volatility", "arch", optional_parameters=("mean", "p", "o", "q", "distribution", "simulations", "seed"), task_parameters=("forecast_steps",)),
    "gjr_tarch": ModelOverride("gjr_tarch", "volatility", "arch", optional_parameters=("mean", "p", "o", "q", "power", "distribution", "simulations", "seed"), task_parameters=("forecast_steps",)),
    "aparch": ModelOverride("aparch", "volatility", "arch", optional_parameters=("mean", "p", "o", "q", "delta", "distribution", "simulations", "seed"), task_parameters=("forecast_steps",), restriction="APARCH delta fixed when supplied, otherwise estimated"),
    "markov_regression": ModelOverride("markov_regression", "regime_state", "statsmodels", optional_parameters=("k_regimes", "trend", "switching_variance", "maxiter"), restriction="filtered/smoothed probabilities; no FR forecast"),
    "markov_autoregression": ModelOverride("markov_autoregression", "regime_state", "statsmodels", optional_parameters=("k_regimes", "order", "trend", "switching_variance", "maxiter"), restriction="filtered/smoothed probabilities; no FR forecast"),
    "state_space": ModelOverride("state_space", "regime_state", "statsmodels", unavailable_reason="generic state_space is not implemented; use explicit unobserved_components"),
    "unobserved_components": ModelOverride("unobserved_components", "regime_state", "statsmodels", optional_parameters=("level",), task_parameters=("forecast_steps",), output_kinds=("conditional_mean",), metrics=("rmse", "mae", "r2"), restriction="explicit structural specification"),
}


_DUAL_TASK_MODELS = {"decision_tree", "random_forest", "extra_trees", "gradient_boosting"}


def capability(model_id: str, *, classification: bool = False, parameters: dict | None = None) -> dict | None:
    model = MODELS.get(model_id)
    if model is None:
        return None
    effective_family = "classification" if classification and model_id in _DUAL_TASK_MODELS else model.family
    family = FAMILIES[effective_family]
    dependency_available = model.adapter == "native" or bool(importlib.util.find_spec(model.adapter))
    reason = model.unavailable_reason or (None if dependency_available else f"optional dependency unavailable: {model.adapter}")
    accepted_parameters = set(model.optional_parameters) | set(model.required_parameters) | set(model.task_parameters)
    output_kinds = model.output_kinds or (family.result_kind,)
    if model_id in _DUAL_TASK_MODELS:
        output_kinds = ("class_label",) if classification else ("numeric_prediction",)
    metrics = family.evaluation_metrics if model.metrics is None or model_id in _DUAL_TASK_MODELS else model.metrics
    if model_id == "fixed_effects" and (parameters or {}).get("time_effects"):
        output_kinds = ("fit_only_diagnostic",)
        metrics = ()
    comparison_group = family.comparison_group if model.comparison_group is None else model.comparison_group
    if model_id == "fixed_effects" and (parameters or {}).get("time_effects"):
        comparison_group = ""
    return {
        "model_id": model_id, "family": effective_family, "input_shape": model.input_shape or family.input_shape,
        "adapter": model.adapter, "available": reason is None, "unavailable_reason": reason,
        "unavailable_kind": "unsupported" if model.unavailable_reason else "dependency" if not dependency_available else None,
        "required_parameters": sorted(model.required_parameters),
        "parameter_contract": {name: {"required": name in model.required_parameters, "accepted": True} for name in sorted(accepted_parameters)},
        "runtime_parameters": sorted(accepted_parameters), "task_parameters": sorted(model.task_parameters),
        "tunable_parameters": sorted(model.tunable_parameters), "supports_tuning": bool(model.tunable_parameters),
        "output_kinds": list(output_kinds), "metrics": list(metrics),
        "supports_forecast": any(kind in {"conditional_mean", "conditional_scenario_mean", "vector_forecast", "conditional_volatility"} for kind in output_kinds),
        "comparison_group": comparison_group,
        "restrictions": [model.restriction] if model.restriction else [],
        "required_inputs": ["Y", "X"] if (model.input_shape or family.input_shape) in {"supervised", "panel"} else ["Y"],
        "supported_tasks": ["regression", "classification"] if model_id in _DUAL_TASK_MODELS else [effective_family],
    }


def inventory() -> list[dict]:
    rows = []
    for model_id in MODELS:
        row = capability(model_id)
        if model_id in _DUAL_TASK_MODELS:
            row["task_modes"] = {
                task: {key: variant[key] for key in ("family", "output_kinds", "metrics", "comparison_group")}
                for task, variant in (("regression", capability(model_id)),
                                      ("classification", capability(model_id, classification=True)))
            }
        if model_id == "fixed_effects":
            row["parameter_modes"] = {
                "time_effects_enabled": {key: capability(model_id, parameters={"time_effects": True})[key]
                                         for key in ("output_kinds", "metrics")}}
        rows.append(row)
    return rows
