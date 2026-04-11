from pathlib import Path
from typing import Dict, List, Optional

from config.settings import SCHEMA_VERSION
from services.period_service import period_sort_tuple
from services.research_utils import now_iso
from utils.file_utils import load_json_file, save_json_file


def _build_actual_registry_path(company_folder: str | Path) -> Path:
    company_folder = Path(company_folder)
    analysis_dir = company_folder / "年报分析"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir / "actual_metrics_registry.json"


def _build_standardized_metrics_path(company_folder: str | Path) -> Path:
    return Path(company_folder) / "年报分析" / "standardized_metrics.json"


def _candidate_sort_key(item: dict):
    extraction_method = item.get("extraction_method", "")
    method_rank = 1 if extraction_method == "table_line" else 0
    has_base = 1 if item.get("value_base") is not None else 0
    score = item.get("score", 0) or 0
    primary_rank = 1 if item.get("allow_into_actuals") or item.get("is_primary_financial_report") else 0
    ts = item.get("material_timestamp", "") or ""
    return (primary_rank, score, method_rank, has_base, ts)


def _pick_best_candidate(candidates: List[dict]) -> Optional[dict]:
    if not candidates:
        return None
    primary_candidates = [item for item in candidates if item.get("allow_into_actuals") or item.get("is_primary_financial_report")]
    if not primary_candidates:
        return None
    return sorted(primary_candidates, key=_candidate_sort_key, reverse=True)[0]


def build_actual_metric_registry(company_folder: str | Path) -> dict:
    company_folder = Path(company_folder)
    standardized_path = _build_standardized_metrics_path(company_folder)

    if not standardized_path.exists():
        output = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "company_name": company_folder.name,
            "actual_metrics": {},
            "status": "missing_standardized_metrics",
        }
        save_json_file(output, _build_actual_registry_path(company_folder))
        return output

    standardized = load_json_file(standardized_path)
    metrics = standardized.get("metrics", {})
    actual_metrics: Dict[str, List[dict]] = {}

    for metric_name, candidates in metrics.items():
        by_period: Dict[str, List[dict]] = {}
        for item in candidates:
            period_key = item.get("period_key", "")
            if not period_key:
                continue
            if not (item.get("allow_into_actuals") or item.get("is_primary_financial_report")):
                continue
            by_period.setdefault(period_key, []).append(item)

        selected_rows = []
        for period_key, rows in by_period.items():
            best = _pick_best_candidate(rows)
            if not best:
                continue
            selected_rows.append({
                "metric_name": metric_name,
                "period_key": best.get("period_key", ""),
                "value": best.get("value"),
                "value_base": best.get("value_base"),
                "prior_value": best.get("prior_value"),
                "prior_value_base": best.get("prior_value_base"),
                "unit": best.get("unit", ""),
                "yoy_percent": best.get("yoy_percent"),
                "qoq_percent": best.get("qoq_percent"),
                "source_file": best.get("source_file", ""),
                "material_timestamp": best.get("material_timestamp", ""),
                "document_type": best.get("document_type", ""),
                "source_role": best.get("source_role", ""),
                "raw_label": best.get("raw_label", ""),
                "snippet": best.get("snippet", ""),
                "extraction_method": best.get("extraction_method", ""),
                "confidence": best.get("confidence", ""),
                "score": best.get("score", 0),
            })

        selected_rows.sort(key=lambda x: period_sort_tuple(x.get("period_key", "")))
        actual_metrics[metric_name] = selected_rows

    output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "status": "ok",
        "actual_metrics": actual_metrics,
    }
    save_json_file(output, _build_actual_registry_path(company_folder))
    return output


def load_actual_metric_registry(company_folder: str | Path) -> dict:
    path = _build_actual_registry_path(company_folder)
    if path.exists():
        return load_json_file(path)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",
        "company_name": Path(company_folder).name,
        "status": "missing",
        "actual_metrics": {},
    }


def get_actual_metric_for_period(company_folder: str | Path, metric_name: str, period_key: str) -> Optional[dict]:
    registry = load_actual_metric_registry(company_folder)
    rows = registry.get("actual_metrics", {}).get(metric_name, [])
    for row in rows:
        if row.get("period_key", "") == period_key:
            return row
    return None
