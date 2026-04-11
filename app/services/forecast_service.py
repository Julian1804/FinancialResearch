import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import SCHEMA_VERSION
from services.actual_metric_service import get_actual_metric_for_period
from services.period_service import period_sort_tuple
from services.provider_service import call_agent_chat
from services.research_utils import now_iso, safe_json_loads
from utils.file_utils import (
    build_forecast_check_json_path,
    build_forecast_registry_path,
    build_forecast_snapshot_json_path,
    build_metric_registry_path,
    get_extracted_json_files_in_company_folder,
    get_forecast_snapshot_files_in_company_folder,
    load_json_file,
    save_json_file,
    sort_paths_by_year_and_name,
)

DEFAULT_FORECAST_METRICS = [
    "revenue",
    "net_profit",
    "gross_margin",
    "operating_cash_flow",
]


def bsts_runtime_status() -> Dict[str, Any]:
    try:
        import numpy  # noqa
        import pandas  # noqa
        import tensorflow  # noqa
        import tensorflow_probability  # noqa
        return {
            "ready": True,
            "message": "BSTS 运行环境已就绪：numpy / pandas / tensorflow / tensorflow_probability 可用。"
        }
    except Exception as e:
        return {
            "ready": False,
            "message": (
                "BSTS 运行环境未就绪。请先安装：\n"
                "pip install numpy pandas tensorflow tensorflow-probability\n"
                f"当前报错：{e}"
            )
        }


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            if math.isnan(float(value)):
                return None
        except Exception:
            pass
        return float(value)

    text = str(value).strip().replace(",", "")
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    text = (text or "").strip()

    if text.startswith("```"):
        text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("模型返回中未找到有效 JSON。")
    return json.loads(text[start:end + 1])


def _load_primary_timeline(company_folder: str | Path) -> List[dict]:
    company_folder = Path(company_folder)
    extracted_files = sort_paths_by_year_and_name(get_extracted_json_files_in_company_folder(company_folder))
    rows = []

    for file_path in extracted_files:
        data = load_json_file(file_path)
        if data.get("is_primary_financial_report"):
            rows.append({
                "period_key": data.get("period_key", ""),
                "report_type": data.get("report_type", ""),
                "source_file": data.get("source_file", Path(file_path).name),
                "material_timestamp": data.get("material_timestamp", ""),
                "document_type": data.get("document_type", ""),
                "report_date": data.get("report_date", ""),
                "fiscal_year": data.get("fiscal_year"),
                "json_path": str(file_path),
            })

    rows.sort(key=lambda x: period_sort_tuple(x.get("period_key", "")))
    return rows


def load_metric_registry(company_folder: str | Path) -> dict:
    path = Path(build_metric_registry_path(company_folder))
    if path.exists():
        try:
            data = load_json_file(path)
            if "primary_timeline" not in data:
                data["primary_timeline"] = _load_primary_timeline(company_folder)
            if "metrics" not in data:
                data["metrics"] = DEFAULT_FORECAST_METRICS
            if "metric_values" not in data:
                data["metric_values"] = {}
            return data
        except Exception:
            pass
    return build_metric_registry_template(company_folder)


def save_metric_registry(company_folder: str | Path, registry: dict) -> None:
    save_json_file(registry, build_metric_registry_path(company_folder))


def build_metric_registry_template(company_folder: str | Path) -> dict:
    company_folder = Path(company_folder)
    primary_timeline = _load_primary_timeline(company_folder)
    registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "primary_timeline": primary_timeline,
        "metrics": DEFAULT_FORECAST_METRICS,
        "metric_values": {},
    }

    for metric_name in DEFAULT_FORECAST_METRICS:
        registry["metric_values"][metric_name] = [
            {
                "period_key": row.get("period_key", ""),
                "report_type": row.get("report_type", ""),
                "source_file": row.get("source_file", ""),
                "material_timestamp": row.get("material_timestamp", ""),
                "value": None,
                "unit": "",
                "notes": "",
            }
            for row in primary_timeline
        ]
    return registry


def _load_metric_table(company_folder: str | Path, metric_name: str) -> List[dict]:
    registry = load_metric_registry(company_folder)
    rows = registry.get("metric_values", {}).get(metric_name, [])
    cleaned_rows = []
    for row in rows:
        cleaned_rows.append({
            "period_key": row.get("period_key", ""),
            "report_type": row.get("report_type", ""),
            "source_file": row.get("source_file", ""),
            "material_timestamp": row.get("material_timestamp", ""),
            "value": _safe_float(row.get("value")),
            "unit": row.get("unit", ""),
            "notes": row.get("notes", ""),
        })
    cleaned_rows.sort(key=lambda x: period_sort_tuple(x.get("period_key", "")))
    return cleaned_rows


def _period_year(period_key: str) -> Optional[int]:
    m = re.match(r"^(19\d{2}|20\d{2})(Q1|H1|Q3|FY)$", str(period_key or ""))
    if not m:
        return None
    return int(m.group(1))


def _period_type(period_key: str) -> str:
    m = re.match(r"^(19\d{2}|20\d{2})(Q1|H1|Q3|FY)$", str(period_key or ""))
    if not m:
        return ""
    return m.group(2)


def _build_series_from_metric_rows(metric_rows: List[dict]) -> Dict[str, float]:
    series = {}
    for row in metric_rows:
        value = _safe_float(row.get("value"))
        period_key = row.get("period_key", "")
        if period_key and value is not None:
            series[period_key] = value
    return series


def _build_fy_series(metric_series: Dict[str, float]) -> List[Tuple[str, float]]:
    items = [(k, v) for k, v in metric_series.items() if _period_type(k) == "FY"]
    items.sort(key=lambda x: period_sort_tuple(x[0]))
    return items


def _historical_bridge_ratios(metric_series: Dict[str, float], partial_type: str) -> List[dict]:
    ratios = []
    years = sorted({_period_year(k) for k in metric_series.keys() if _period_year(k) is not None})
    for year in years:
        partial_key = f"{year}{partial_type}"
        fy_key = f"{year}FY"
        partial_val = metric_series.get(partial_key)
        fy_val = metric_series.get(fy_key)
        if partial_val is None or fy_val is None:
            continue
        if fy_val == 0:
            continue
        ratio = partial_val / fy_val
        ratios.append({
            "year": year,
            "partial_key": partial_key,
            "fy_key": fy_key,
            "partial_value": partial_val,
            "fy_value": fy_val,
            "ratio": ratio,
        })
    return ratios


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    n = len(values)
    if n % 2 == 1:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / 2.0


def _bridge_estimate(metric_series: Dict[str, float], anchor_period: str) -> Dict[str, Any]:
    p_type = _period_type(anchor_period)
    year = _period_year(anchor_period)
    current_value = metric_series.get(anchor_period)

    if p_type not in {"Q1", "H1", "Q3"} or year is None or current_value is None:
        return {
            "available": False,
            "reason": "anchor 不是 Q1/H1/Q3，或当前 partial 数值缺失。",
            "partial_type": p_type,
            "current_partial_value": current_value,
            "historical_ratios": [],
            "median_ratio": None,
            "estimated_fy": None,
        }

    ratios = _historical_bridge_ratios(metric_series, p_type)
    ratio_values = [item["ratio"] for item in ratios if item["ratio"] > 0]
    median_ratio = _median(ratio_values)

    if median_ratio is None or median_ratio == 0:
        return {
            "available": False,
            "reason": "缺少历史 partial/FY 配对样本。",
            "partial_type": p_type,
            "current_partial_value": current_value,
            "historical_ratios": ratios,
            "median_ratio": None,
            "estimated_fy": None,
        }

    estimated_fy = current_value / median_ratio
    return {
        "available": True,
        "reason": "",
        "partial_type": p_type,
        "current_partial_value": current_value,
        "historical_ratios": ratios,
        "median_ratio": median_ratio,
        "estimated_fy": estimated_fy,
    }


def _run_bsts_annual_forecast(
    fy_series: List[Tuple[str, float]],
    forecast_horizon: int = 1,
    confidence_level: float = 0.8,
    hmc_draws: int = 120,
    hmc_burnin: int = 80,
) -> Dict[str, Any]:
    runtime = bsts_runtime_status()
    if not runtime["ready"]:
        return {
            "status": "runtime_not_ready",
            "message": runtime["message"],
        }

    if len(fy_series) < 3:
        return {
            "status": "insufficient_data",
            "message": "FY 样本不足，至少需要 3 个 FY 点。",
        }

    import numpy as np
    import tensorflow as tf
    import tensorflow_probability as tfp

    tf.random.set_seed(42)
    sts = tfp.sts

    periods = [item[0] for item in fy_series]
    y = np.array([float(item[1]) for item in fy_series], dtype=np.float32)
    observed_time_series = y[..., np.newaxis]

    model = sts.Sum(
        components=[
            sts.LocalLinearTrend(observed_time_series=observed_time_series, name="trend"),
        ],
        observed_time_series=observed_time_series,
    )

    surrogate_posterior = tfp.sts.build_factored_surrogate_posterior(model=model)
    optimizer = tf.optimizers.Adam(learning_rate=0.1)

    @tf.function(autograph=False)
    def train():
        return tfp.vi.fit_surrogate_posterior(
            target_log_prob_fn=model.joint_distribution(observed_time_series).log_prob,
            surrogate_posterior=surrogate_posterior,
            optimizer=optimizer,
            num_steps=200,
        )

    train()

    q_samples = surrogate_posterior.sample(64)
    forecast_dist = tfp.sts.forecast(
        model=model,
        observed_time_series=observed_time_series,
        parameter_samples=q_samples,
        num_steps_forecast=forecast_horizon,
    )

    mean_forecast = forecast_dist.mean().numpy().reshape(-1).tolist()
    lower_q = (1.0 - confidence_level) / 2.0
    upper_q = 1.0 - lower_q
    lower = forecast_dist.quantile(lower_q).numpy().reshape(-1).tolist()
    upper = forecast_dist.quantile(upper_q).numpy().reshape(-1).tolist()

    residual_std = float(np.std(y)) if len(y) > 1 else 0.0

    return {
        "status": "ok",
        "message": "BSTS forecast completed.",
        "history_periods": periods,
        "history_values": y.tolist(),
        "forecast_horizon": forecast_horizon,
        "confidence_level": confidence_level,
        "forecast_mean": mean_forecast,
        "forecast_lower": lower,
        "forecast_upper": upper,
        "residual_std_proxy": residual_std,
        "hmc_draws": hmc_draws,
        "hmc_burnin": hmc_burnin,
    }


def _determine_target_period(anchor_period: str) -> str:
    year = _period_year(anchor_period)
    rtype = _period_type(anchor_period)

    if year is None or rtype == "":
        return ""

    if rtype in {"Q1", "H1", "Q3"}:
        return f"{year}FY"
    if rtype == "FY":
        return f"{year + 1}FY"
    return ""


def _combine_base_and_bridge(
    annual_base: Optional[float],
    annual_lower: Optional[float],
    annual_upper: Optional[float],
    bridge_estimated_fy: Optional[float],
    anchor_type: str,
) -> Dict[str, Any]:
    if anchor_type == "FY":
        return {
            "base": annual_base,
            "lower": annual_lower,
            "upper": annual_upper,
            "combination_rule": "FY 时点仅使用 annual BSTS。",
            "bridge_weight": 0.0,
            "annual_weight": 1.0,
        }

    if bridge_estimated_fy is None and annual_base is not None:
        return {
            "base": annual_base,
            "lower": annual_lower,
            "upper": annual_upper,
            "combination_rule": "无 bridge estimate，仅使用 annual BSTS。",
            "bridge_weight": 0.0,
            "annual_weight": 1.0,
        }

    if annual_base is None and bridge_estimated_fy is not None:
        spread = abs(bridge_estimated_fy) * 0.1
        return {
            "base": bridge_estimated_fy,
            "lower": bridge_estimated_fy - spread,
            "upper": bridge_estimated_fy + spread,
            "combination_rule": "无 annual BSTS，有 bridge estimate，使用 bridge 作为基准。",
            "bridge_weight": 1.0,
            "annual_weight": 0.0,
        }

    if annual_base is None and bridge_estimated_fy is None:
        return {
            "base": None,
            "lower": None,
            "upper": None,
            "combination_rule": "annual 与 bridge 都不可用。",
            "bridge_weight": 0.0,
            "annual_weight": 0.0,
        }

    annual_weight = 0.45
    bridge_weight = 0.55
    base = annual_base * annual_weight + bridge_estimated_fy * bridge_weight

    lower_candidates = [x for x in [annual_lower, bridge_estimated_fy * 0.92] if x is not None]
    upper_candidates = [x for x in [annual_upper, bridge_estimated_fy * 1.08] if x is not None]

    return {
        "base": base,
        "lower": min(lower_candidates) if lower_candidates else None,
        "upper": max(upper_candidates) if upper_candidates else None,
        "combination_rule": "partial 时点采用 annual BSTS + historical bridge 混合。",
        "bridge_weight": bridge_weight,
        "annual_weight": annual_weight,
    }


def _scenario_bundle(base: Optional[float], lower: Optional[float], upper: Optional[float], unit: str = "") -> Dict[str, Any]:
    if base is None:
        return {
            "bull": {"value": None, "unit": unit},
            "base": {"value": None, "unit": unit},
            "bear": {"value": None, "unit": unit},
        }

    bull_value = upper if upper is not None else base * 1.08
    bear_value = lower if lower is not None else base * 0.92

    return {
        "bull": {"value": bull_value, "unit": unit},
        "base": {"value": base, "unit": unit},
        "bear": {"value": bear_value, "unit": unit},
    }


def _build_forecast_reasoning_prompt(snapshot_core: dict) -> str:
    return f"""
你是一名财报预测解释助手。你只需要基于给定的量化预测结果，给出克制、证据驱动的解释。

要求：
1. 不许编造新数据。
2. 只能基于输入中的 annual_bsts、bridge_model、scenario_bundle、historical_series 来解释。
3. 用中文输出 JSON。
4. bull/base/bear 都要给：view / quantitative_targets / drivers / trigger_conditions / falsifiers
5. final_summary 要明确：
   - 这是站在什么时点做的预测
   - 为什么不是更乐观
   - 为什么不是更悲观
""".strip()


def _llm_enrich_snapshot(snapshot_core: dict) -> dict:
    try:
        raw = call_agent_chat(
            "analysis_agent",
            "你是一名预测解释助手，只输出 JSON。",
            _build_forecast_reasoning_prompt(snapshot_core) + "\n\n" + json.dumps(snapshot_core, ensure_ascii=False, indent=2),
        )
        return safe_json_loads(raw)
    except Exception:
        return {}


def load_forecast_registry(company_folder: str | Path) -> dict:
    company_folder = Path(company_folder)
    path = Path(build_forecast_registry_path(company_folder))
    if path.exists():
        try:
            return load_json_file(path)
        except Exception:
            pass
    return {
        "schema_version": SCHEMA_VERSION,
        "company_name": company_folder.name,
        "generated_at": "",
        "snapshots": [],
    }


def _append_forecast_registry(company_folder: str | Path, snapshot: dict) -> dict:
    company_folder = Path(company_folder)
    registry = load_forecast_registry(company_folder)

    entry = {
        "generated_at": snapshot.get("generated_at", ""),
        "metric_name": snapshot.get("metric_name", ""),
        "forecast_as_of_period": snapshot.get("forecast_as_of_period", ""),
        "forecast_target_period": snapshot.get("forecast_target_period", ""),
        "anchor_report_type": snapshot.get("anchor_report_type", ""),
        "snapshot_path": snapshot.get("snapshot_path", ""),
        "status": snapshot.get("status", ""),
        "base_value": snapshot.get("scenario_bundle", {}).get("base", {}).get("value"),
        "bull_value": snapshot.get("scenario_bundle", {}).get("bull", {}).get("value"),
        "bear_value": snapshot.get("scenario_bundle", {}).get("bear", {}).get("value"),
        "unit": snapshot.get("unit", ""),
    }

    registry["snapshots"] = [s for s in registry.get("snapshots", []) if s.get("snapshot_path") != entry.get("snapshot_path")]
    registry["snapshots"].append(entry)
    registry["generated_at"] = now_iso()
    save_json_file(registry, build_forecast_registry_path(company_folder))
    return registry


def generate_forecast_snapshot(
    company_folder: str | Path,
    metric_name: str,
    anchor_period: str,
    confidence_level: float = 0.8,
    hmc_draws: int = 120,
    hmc_burnin: int = 80,
) -> dict:
    company_folder = Path(company_folder)
    metric_rows = _load_metric_table(company_folder, metric_name)
    metric_series = _build_series_from_metric_rows(metric_rows)

    anchor_type = _period_type(anchor_period)
    target_period = _determine_target_period(anchor_period)

    anchor_row = next((row for row in metric_rows if row.get("period_key") == anchor_period), {})
    unit = anchor_row.get("unit", "")

    fy_series = _build_fy_series(metric_series)

    annual_bsts = _run_bsts_annual_forecast(
        fy_series=fy_series,
        forecast_horizon=1,
        confidence_level=confidence_level,
        hmc_draws=hmc_draws,
        hmc_burnin=hmc_burnin,
    )

    annual_base = None
    annual_lower = None
    annual_upper = None

    if annual_bsts.get("status") == "ok":
        annual_base = annual_bsts["forecast_mean"][0]
        annual_lower = annual_bsts["forecast_lower"][0]
        annual_upper = annual_bsts["forecast_upper"][0]

    bridge = _bridge_estimate(metric_series, anchor_period)

    combo = _combine_base_and_bridge(
        annual_base=annual_base,
        annual_lower=annual_lower,
        annual_upper=annual_upper,
        bridge_estimated_fy=bridge.get("estimated_fy"),
        anchor_type=anchor_type,
    )

    scenario_bundle = _scenario_bundle(
        base=combo.get("base"),
        lower=combo.get("lower"),
        upper=combo.get("upper"),
        unit=unit,
    )

    snapshot_status = "ok"
    reasons = []

    if combo.get("base") is None:
        snapshot_status = "insufficient_data"
        reasons.append("annual BSTS 与 bridge estimate 均不可用。")

    if annual_bsts.get("status") != "ok":
        reasons.append(f"annual_bsts={annual_bsts.get('status')}: {annual_bsts.get('message', '')}")

    if not bridge.get("available") and anchor_type in {"Q1", "H1", "Q3"}:
        reasons.append(f"bridge_unavailable: {bridge.get('reason', '')}")

    snapshot_core = {
        "company_name": company_folder.name,
        "metric_name": metric_name,
        "forecast_as_of_period": anchor_period,
        "forecast_target_period": target_period,
        "anchor_report_type": anchor_type,
        "confidence_level": confidence_level,
        "unit": unit,
        "historical_series": metric_rows,
        "annual_bsts": annual_bsts,
        "bridge_model": bridge,
        "combination": combo,
        "scenario_bundle": scenario_bundle,
        "status": snapshot_status,
        "status_reasons": reasons,
    }

    llm_explained = _llm_enrich_snapshot(snapshot_core)

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "metric_name": metric_name,
        "forecast_as_of_period": anchor_period,
        "forecast_target_period": target_period,
        "anchor_report_type": anchor_type,
        "confidence_level": confidence_level,
        "status": snapshot_status,
        "status_reasons": reasons,
        "unit": unit,
        "historical_series": metric_rows,
        "annual_bsts": annual_bsts,
        "bridge_model": bridge,
        "combination": combo,
        "scenario_bundle": scenario_bundle,
        "llm_explanation": llm_explained,
    }

    snapshot_path = build_forecast_snapshot_json_path(
        company_folder=company_folder,
        metric_name=metric_name,
        forecast_as_of_period=anchor_period,
        forecast_target_period=target_period,
    )
    snapshot["snapshot_path"] = snapshot_path
    save_json_file(snapshot, snapshot_path)

    registry_data = _append_forecast_registry(company_folder, snapshot)
    snapshot["forecast_registry_path"] = build_forecast_registry_path(company_folder)
    snapshot["forecast_registry_size"] = len(registry_data.get("snapshots", []))
    save_json_file(snapshot, snapshot_path)

    return snapshot


def build_forecast_overview_rows(company_folder: str | Path) -> List[dict]:
    company_folder = Path(company_folder)
    files = sort_paths_by_year_and_name(get_forecast_snapshot_files_in_company_folder(company_folder))
    rows = []

    for file_path in files:
        try:
            data = load_json_file(file_path)
        except Exception:
            continue

        rows.append({
            "generated_at": data.get("generated_at", ""),
            "metric_name": data.get("metric_name", ""),
            "forecast_as_of_period": data.get("forecast_as_of_period", ""),
            "forecast_target_period": data.get("forecast_target_period", ""),
            "anchor_report_type": data.get("anchor_report_type", ""),
            "status": data.get("status", ""),
            "bull_value": data.get("scenario_bundle", {}).get("bull", {}).get("value"),
            "base_value": data.get("scenario_bundle", {}).get("base", {}).get("value"),
            "bear_value": data.get("scenario_bundle", {}).get("bear", {}).get("value"),
            "unit": data.get("unit", ""),
            "snapshot_path": str(file_path),
        })

    rows.sort(key=lambda x: (x.get("forecast_as_of_period", ""), x.get("metric_name", ""), x.get("generated_at", "")))
    return rows


def build_snapshot_matrix(rows: List[dict]) -> List[dict]:
    grouped: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for row in rows:
        key = (row.get("forecast_as_of_period", ""), row.get("forecast_target_period", ""))
        grouped.setdefault(key, {
            "forecast_as_of_period": row.get("forecast_as_of_period", ""),
            "forecast_target_period": row.get("forecast_target_period", ""),
        })

        metric = row.get("metric_name", "")
        unit = row.get("unit", "")

        grouped[key][f"{metric}_bull"] = row.get("bull_value")
        grouped[key][f"{metric}_base"] = row.get("base_value")
        grouped[key][f"{metric}_bear"] = row.get("bear_value")
        grouped[key][f"{metric}_unit"] = unit

    matrix_rows = list(grouped.values())
    matrix_rows.sort(key=lambda x: (x.get("forecast_as_of_period", ""), x.get("forecast_target_period", "")))
    return matrix_rows


def _find_best_snapshot_for_check(company_folder: str | Path, actual_extracted: dict) -> Optional[dict]:
    target_period = actual_extracted.get("forecast_target_period", "")
    actual_observation_period = actual_extracted.get("period_key", "")

    if not target_period:
        return None

    candidates = []
    for row in build_forecast_overview_rows(company_folder):
        if row.get("forecast_target_period") != target_period:
            continue
        as_of = row.get("forecast_as_of_period", "")
        if as_of and actual_observation_period and period_sort_tuple(as_of) <= period_sort_tuple(actual_observation_period):
            candidates.append(row)

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x.get("forecast_as_of_period", ""), x.get("generated_at", "")))
    return candidates[-1]


def build_snapshot_auto_match(company_folder: str | Path, actual_extracted: dict) -> dict:
    best = _find_best_snapshot_for_check(company_folder, actual_extracted)
    if not best:
        return {
            "matched": False,
            "reason": "未找到与当前观察期匹配的 snapshot。",
        }

    snapshot_path = best.get("snapshot_path", "")
    if not snapshot_path or not Path(snapshot_path).exists():
        return {
            "matched": False,
            "reason": "匹配到 snapshot 记录，但文件不存在。",
        }

    data = load_json_file(snapshot_path)
    return {
        "matched": True,
        "reason": "",
        "snapshot": data,
    }


def _build_partial_expected_from_snapshot(
    company_folder: str | Path,
    snapshot: dict,
    actual_period: str,
) -> dict:
    metric_name = snapshot.get("metric_name", "")
    metric_rows = _load_metric_table(company_folder, metric_name)
    metric_series = _build_series_from_metric_rows(metric_rows)

    partial_type = _period_type(actual_period)
    ratios = _historical_bridge_ratios(metric_series, partial_type)
    ratio_values = [item["ratio"] for item in ratios if item["ratio"] is not None and item["ratio"] > 0]
    median_ratio = _median(ratio_values)

    if median_ratio is None:
        return {
            "available": False,
            "reason": "缺少历史 partial/FY ratio 样本。",
        }

    bull = _safe_float(snapshot.get("scenario_bundle", {}).get("bull", {}).get("value"))
    base = _safe_float(snapshot.get("scenario_bundle", {}).get("base", {}).get("value"))
    bear = _safe_float(snapshot.get("scenario_bundle", {}).get("bear", {}).get("value"))

    return {
        "available": True,
        "reason": "",
        "partial_type": partial_type,
        "median_ratio": median_ratio,
        "expected_partial_bull": bull * median_ratio if bull is not None else None,
        "expected_partial_base": base * median_ratio if base is not None else None,
        "expected_partial_bear": bear * median_ratio if bear is not None else None,
        "historical_ratios": ratios,
    }


def _compute_match_level(actual_value: Optional[float], low: Optional[float], high: Optional[float], base: Optional[float]) -> str:
    if actual_value is None or base is None:
        return "信息不足"

    if low is not None and high is not None and low <= actual_value <= high:
        return "符合"

    if base == 0:
        return "部分符合"

    deviation_pct = abs(actual_value - base) / abs(base)
    if deviation_pct <= 0.15:
        return "部分符合"
    return "明显偏离"


def build_snapshot_actual_auto_compare(
    company_folder: str | Path,
    snapshot: dict,
    actual_extracted: dict,
) -> dict:
    company_folder = Path(company_folder)
    metric_name = snapshot.get("metric_name", "")
    actual_period = actual_extracted.get("period_key", "")
    target_period = snapshot.get("forecast_target_period", "")
    unit = snapshot.get("unit", "")

    actual_row = get_actual_metric_for_period(company_folder, metric_name, actual_period)
    if not actual_row:
        return {
            "matched": False,
            "reason": f"actual_metrics_registry 中未找到 metric={metric_name}, period={actual_period} 的实际值。",
        }

    actual_value = actual_row.get("value")
    actual_value_base = actual_row.get("value_base")
    actual_numeric = actual_value_base if actual_value_base is not None else actual_value

    snapshot_bull = _safe_float(snapshot.get("scenario_bundle", {}).get("bull", {}).get("value"))
    snapshot_base = _safe_float(snapshot.get("scenario_bundle", {}).get("base", {}).get("value"))
    snapshot_bear = _safe_float(snapshot.get("scenario_bundle", {}).get("bear", {}).get("value"))

    if actual_period == target_period:
        expected_low = snapshot_bear
        expected_high = snapshot_bull
        expected_base = snapshot_base
        match_level = _compute_match_level(actual_numeric, expected_low, expected_high, expected_base)

        deviation_abs = (actual_numeric - expected_base) if (actual_numeric is not None and expected_base is not None) else None
        deviation_pct = ((actual_numeric - expected_base) / expected_base) if (
            actual_numeric is not None and expected_base not in [None, 0]
        ) else None

        return {
            "matched": True,
            "comparison_basis": "target_period_actual_vs_snapshot_target",
            "metric_name": metric_name,
            "actual_period": actual_period,
            "target_period": target_period,
            "unit": unit,
            "actual_value": actual_numeric,
            "expected_bull": snapshot_bull,
            "expected_base": snapshot_base,
            "expected_bear": snapshot_bear,
            "within_expected_range": (
                actual_numeric is not None and expected_low is not None and expected_high is not None
                and expected_low <= actual_numeric <= expected_high
            ),
            "deviation_abs": deviation_abs,
            "deviation_pct": deviation_pct,
            "prediction_match_level_auto": match_level,
            "actual_source_file": actual_row.get("source_file", ""),
            "actual_snippet": actual_row.get("snippet", ""),
        }

    actual_year = _period_year(actual_period)
    target_year = _period_year(target_period)
    actual_type = _period_type(actual_period)

    if actual_year is not None and target_year is not None and actual_year == target_year and actual_type in {"Q1", "H1", "Q3"}:
        partial_expected = _build_partial_expected_from_snapshot(company_folder, snapshot, actual_period)
        if not partial_expected.get("available"):
            return {
                "matched": False,
                "reason": partial_expected.get("reason", "partial expected 不可用。"),
            }

        expected_bull = partial_expected.get("expected_partial_bull")
        expected_base = partial_expected.get("expected_partial_base")
        expected_bear = partial_expected.get("expected_partial_bear")

        match_level = _compute_match_level(actual_numeric, expected_bear, expected_bull, expected_base)
        deviation_abs = (actual_numeric - expected_base) if (actual_numeric is not None and expected_base is not None) else None
        deviation_pct = ((actual_numeric - expected_base) / expected_base) if (
            actual_numeric is not None and expected_base not in [None, 0]
        ) else None

        return {
            "matched": True,
            "comparison_basis": "partial_actual_vs_snapshot_implied_partial",
            "metric_name": metric_name,
            "actual_period": actual_period,
            "target_period": target_period,
            "unit": unit,
            "actual_value": actual_numeric,
            "expected_bull": expected_bull,
            "expected_base": expected_base,
            "expected_bear": expected_bear,
            "within_expected_range": (
                actual_numeric is not None and expected_bear is not None and expected_bull is not None
                and expected_bear <= actual_numeric <= expected_bull
            ),
            "deviation_abs": deviation_abs,
            "deviation_pct": deviation_pct,
            "prediction_match_level_auto": match_level,
            "median_ratio": partial_expected.get("median_ratio"),
            "actual_source_file": actual_row.get("source_file", ""),
            "actual_snippet": actual_row.get("snippet", ""),
        }

    return {
        "matched": False,
        "reason": "当前观察期与 snapshot target period 之间无法建立自动数值比较规则。",
    }


def build_forecast_check_system_prompt() -> str:
    return """
你是一名专业、克制、易懂的预测回测与偏差分析助手。

你的任务是：
1. 优先读取“forecast snapshot”（即过去时点做出的正式量化预测）
2. 读取系统自动计算出的 actual vs snapshot 硬数值偏差
3. 再结合基准报告（如果有）与当前观察期材料
4. 判断：过去的全年预期，在当前观察期看来，是“符合、部分符合、明显偏离”还是“信息不足”
5. 分析偏差来源
6. 给出更新建议

注意：
- 如果系统已经给出了 auto comparison，请优先尊重这个硬数值比较结果。
- 你可以解释，但不要无视数值结果。
- 如果当前观察期只是 Q1/H1/Q3，这属于滚动回测，不是最终全年验收。
- 如果 snapshot 与 report 同时存在，应以 snapshot 的量化结果为主，report 的文字判断为辅。

输出必须是纯 JSON，不要加 Markdown。
JSON 顶层字段必须严格包含：
{
  "company_name": "",
  "forecast_as_of_period": "",
  "forecast_target_period": "",
  "actual_observation_period": "",
  "actual_document_type": "",
  "metric_name": "",
  "snapshot_used": true,
  "comparison_basis": "",
  "snapshot_base_value": null,
  "snapshot_bull_value": null,
  "snapshot_bear_value": null,
  "actual_current_value": null,
  "expected_current_value": null,
  "deviation_abs": null,
  "deviation_pct": null,
  "previous_recommendation": "",
  "updated_recommendation": "",
  "prediction_match_level": "符合/部分符合/明显偏离/信息不足",
  "matched_points": [],
  "missed_points": [],
  "surprise_points": [],
  "deviation_sources": {
    "macro": [],
    "industry": [],
    "company_specific": [],
    "analysis_bias": []
  },
  "framework_feedback": {
    "which_signals_worked": [],
    "which_signals_failed": [],
    "suggested_framework_adjustments": []
  },
  "summary": ""
}
""".strip()


def build_forecast_check_user_prompt(
    base_report: dict,
    actual_parsed: dict,
    actual_extracted: dict,
    snapshot: Optional[dict] = None,
    auto_comparison: Optional[dict] = None,
) -> str:
    payload = {
        "snapshot": snapshot or {},
        "auto_comparison": auto_comparison or {},
        "base_report": {
            "company_name": base_report.get("company_name", ""),
            "fiscal_year": base_report.get("fiscal_year"),
            "report_type": base_report.get("report_type", ""),
            "period_key": base_report.get("period_key", ""),
            "document_type": base_report.get("document_type", ""),
            "forecast_as_of_period": base_report.get("forecast_as_of_period", ""),
            "forecast_target_period": base_report.get("forecast_target_period", ""),
            "risk_analysis": base_report.get("risk_analysis", {}),
            "forecast": base_report.get("forecast", {}),
            "final_conclusion": base_report.get("final_conclusion", {})
        },
        "actual_extracted": {
            "company_name": actual_extracted.get("company_name", ""),
            "fiscal_year": actual_extracted.get("fiscal_year"),
            "report_type": actual_extracted.get("report_type", ""),
            "period_key": actual_extracted.get("period_key", ""),
            "document_type": actual_extracted.get("document_type", ""),
            "report_date": actual_extracted.get("report_date", ""),
            "material_timestamp": actual_extracted.get("material_timestamp", ""),
            "is_primary_financial_report": actual_extracted.get("is_primary_financial_report", False),
            "can_adjust_forecast": actual_extracted.get("can_adjust_forecast", False),
            "forecast_as_of_period": actual_extracted.get("forecast_as_of_period", ""),
            "forecast_target_period": actual_extracted.get("forecast_target_period", ""),
            "key_sections": actual_extracted.get("key_sections", {})
        },
        "actual_parsed_preview": actual_parsed.get("full_text", "")[:15000]
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_forecast_check(
    base_report: dict,
    actual_parsed: dict,
    actual_extracted: dict,
    snapshot: Optional[dict] = None,
    auto_comparison: Optional[dict] = None,
) -> dict:
    system_prompt = build_forecast_check_system_prompt()
    user_prompt = build_forecast_check_user_prompt(
        base_report=base_report,
        actual_parsed=actual_parsed,
        actual_extracted=actual_extracted,
        snapshot=snapshot,
        auto_comparison=auto_comparison,
    )

    raw_output = call_agent_chat("analysis_agent", system_prompt, user_prompt)
    result = _extract_json_from_text(raw_output)

    result["company_name"] = actual_extracted.get("company_name", result.get("company_name", ""))
    result["forecast_as_of_period"] = (
        (snapshot or {}).get("forecast_as_of_period")
        or base_report.get("forecast_as_of_period", result.get("forecast_as_of_period", ""))
    )
    result["forecast_target_period"] = (
        (snapshot or {}).get("forecast_target_period")
        or base_report.get("forecast_target_period", result.get("forecast_target_period", ""))
    )
    result["actual_observation_period"] = actual_extracted.get("period_key", result.get("actual_observation_period", ""))
    result["actual_document_type"] = actual_extracted.get("document_type", result.get("actual_document_type", ""))

    if snapshot:
        result["snapshot_used"] = True
        result["metric_name"] = snapshot.get("metric_name", result.get("metric_name", ""))
        result["snapshot_base_value"] = snapshot.get("scenario_bundle", {}).get("base", {}).get("value")
        result["snapshot_bull_value"] = snapshot.get("scenario_bundle", {}).get("bull", {}).get("value")
        result["snapshot_bear_value"] = snapshot.get("scenario_bundle", {}).get("bear", {}).get("value")
    else:
        result["snapshot_used"] = False
        result.setdefault("metric_name", "")
        result.setdefault("snapshot_base_value", None)
        result.setdefault("snapshot_bull_value", None)
        result.setdefault("snapshot_bear_value", None)

    if auto_comparison and auto_comparison.get("matched"):
        result["comparison_basis"] = auto_comparison.get("comparison_basis", "")
        result["actual_current_value"] = auto_comparison.get("actual_value")
        result["expected_current_value"] = auto_comparison.get("expected_base")
        result["deviation_abs"] = auto_comparison.get("deviation_abs")
        result["deviation_pct"] = auto_comparison.get("deviation_pct")
        if not result.get("prediction_match_level"):
            result["prediction_match_level"] = auto_comparison.get("prediction_match_level_auto", "信息不足")
    else:
        result.setdefault("comparison_basis", "")
        result.setdefault("actual_current_value", None)
        result.setdefault("expected_current_value", None)
        result.setdefault("deviation_abs", None)
        result.setdefault("deviation_pct", None)

    if not result.get("previous_recommendation"):
        result["previous_recommendation"] = (
            base_report.get("forecast", {}).get("next_year_view", "")
            or base_report.get("final_conclusion", {}).get("stance", "")
            or ((snapshot or {}).get("llm_explanation", {}).get("final_summary", {}).get("stance", ""))
        )

    if not result.get("updated_recommendation"):
        result["updated_recommendation"] = result.get("previous_recommendation", "") or "信息不足"

    result["generated_at"] = now_iso()
    result["schema_version"] = SCHEMA_VERSION

    return result