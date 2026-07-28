"""Validate the active unified dataset and metric registries without I/O side effects."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "config" / "fr_dataset_registry.json"
DATASET_SCHEMA_PATH = ROOT / "config" / "fr_dataset_registry.schema.json"
METRIC_PATH = ROOT / "config" / "metrics_registry.json"
ACTIVE_TEXT_SCAN_EXCLUDES = {
    ROOT / "config" / "fr_public_source_manifest.json",
}
REQUIRED_METRIC_FIELDS = {
    "metric_id",
    "chinese_name",
    "english_name",
    "financial_definition",
    "domain",
    "value_type",
    "canonical_unit",
    "required_subject_type",
    "currency_role",
    "currency_rule",
    "canonical_scale",
    "date_time_contract",
    "grain",
    "required_series_dimensions",
    "series_invariant_dimensions",
    "fact_varying_dimensions",
    "report_accounting_context",
    "adjustment_share_class_rules",
    "allowed_aliases",
    "prohibited_automatic_aliases",
    "source_field_mapping_evidence",
    "unit_conversion_rules",
    "currency_conversion_rules",
    "version_effective_date_rules",
    "conflict_tolerance_rules",
    "direct_derived_preference",
    "applicability_coverage_rule",
    "domain_authority_source_rule",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    datasets = read_json(DATASET_PATH)
    schema = read_json(DATASET_SCHEMA_PATH)
    metrics = read_json(METRIC_PATH)
    failures: list[str] = []
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(datasets, schema)
        schema_status = "jsonschema_validated"
    except ImportError:
        schema_status = "jsonschema_not_installed"
    except Exception as exc:
        schema_status = "jsonschema_failed"
        failures.append(str(exc))

    dataset_ids = [item["dataset_id"] for item in datasets["datasets"]]
    if len(dataset_ids) != len(set(dataset_ids)):
        failures.append("duplicate dataset_id")
    layers = Counter(item["layer"] for item in datasets["datasets"])
    if layers["standard_facts"] != 1:
        failures.append("exactly one standard_facts registry row is required")
    if layers["source_observations"] == 0 or layers["read_models"] == 0:
        failures.append("source-observation and read-model rows are required")

    metric_rows = metrics.get("metrics", [])
    metric_ids = [item.get("metric_id") for item in metric_rows]
    if metrics.get("schema_version") != "fr_unified_metric_registry_v1":
        failures.append("wrong metric registry schema")
    if len(metric_ids) != len(set(metric_ids)):
        failures.append("duplicate metric_id")
    for item in metric_rows:
        missing = sorted(REQUIRED_METRIC_FIELDS - item.keys())
        if missing:
            failures.append(f"{item.get('metric_id')} missing {missing}")

    active_text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for base in (ROOT / "config", ROOT / "data_source_contracts")
        for path in base.rglob("*")
        if path.is_file() and "archive" not in path.parts and path not in ACTIVE_TEXT_SCAN_EXCLUDES
    )
    forbidden_terms = (
        "canonical" + "_data_id",
        "natural" + "_key",
        "idempotency" + "_key",
        "investment" + "_id",
    )
    for forbidden in forbidden_terms:
        if forbidden in active_text:
            failures.append(f"active config contains forbidden term: {forbidden}")

    summary = {
        "schema_status": schema_status,
        "dataset_count": len(dataset_ids),
        "layer_counts": dict(layers),
        "metric_registry_count": len(metric_ids),
        "failure_count": len(failures),
        "failures": failures,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
