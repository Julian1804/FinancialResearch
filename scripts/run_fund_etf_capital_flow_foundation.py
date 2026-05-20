from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_morningstar_safe_access_audit import read_json, write_json, write_text  # noqa: E402


CONFIG_ROOT = PROJECT_ROOT / "config"
DOCS_ROOT = PROJECT_ROOT / "docs"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "fund_etf_capital_flow"
TEMPLATE_ROOT = RUNTIME_ROOT / "manual_import_templates"
MORNINGSTAR_VALIDATION_ROOT = PROJECT_ROOT / "runtime" / "morningstar_fund_validation"
MORNINGSTAR_PILOT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_connector_pilot"
AUTHORITATIVE_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("鈥?", "-").replace("鈥", "-").replace("�", "-").replace("–", "-")


def schema_fields() -> dict[str, list[str]]:
    return {
        "fund_master": [
            "dataset_id",
            "source_id",
            "fund_id",
            "fund_code",
            "fund_name",
            "fund_type",
            "fund_company",
            "domicile",
            "market",
            "currency",
            "inception_date",
            "isin",
            "ticker",
            "exchange",
            "morningstar_sec_id",
            "official_source_id",
            "source_priority",
            "publish_date",
            "retrieved_at",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "etf_market_data": [
            "dataset_id",
            "source_id",
            "etf_code",
            "etf_name",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "turnover_rate",
            "nav",
            "premium_discount",
            "shares_outstanding",
            "aum",
            "currency",
            "exchange",
            "publish_date",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "holdings": [
            "dataset_id",
            "source_id",
            "fund_id",
            "holding_date",
            "holding_name",
            "holding_code",
            "holding_identifier",
            "asset_type",
            "weight",
            "shares",
            "market_value",
            "sector",
            "country",
            "currency",
            "publish_date",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "flow_proxy": [
            "dataset_id",
            "source_id",
            "fund_id_or_etf_code",
            "observation_date",
            "proxy_type",
            "proxy_value",
            "unit",
            "confidence",
            "limitation_note",
            "not_actual_flow_warning",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
    }


def write_data_model() -> dict[str, Any]:
    schemas = schema_fields()
    taxonomy = {
        "version": "fund_etf_taxonomy_v1",
        "generated_at": utc_now(),
        "domains": ["fund_market", "etf_market", "capital_flow_proxy", "holdings", "licensed_source"],
        "fund_types": ["mutual_fund", "etf", "lof", "money_market_fund", "index_fund", "closed_end_fund", "unknown"],
        "flow_proxy_types": [
            "volume",
            "amount",
            "shares_outstanding_change",
            "aum_change",
            "nav_change",
            "holdings_change",
            "premium_discount",
        ],
        "trust_statuses": [
            "official_source_candidate",
            "licensed_source_candidate",
            "coverage_validated_candidate",
            "cross_validated_candidate",
            "trusted_candidate",
            "needs_review",
        ],
        "source_priority": {
            "china_official_list": 1,
            "exchange_disclosure": 1,
            "issuer_official": 1,
            "morningstar_direct": 2,
            "third_party_candidate": 3,
        },
        "flow_proxy_warning": "Flow proxy is not actual net flow unless source field explicitly represents flow.",
    }
    summary = {
        "generated_at": utc_now(),
        "schemas": {name: {"fields": fields, "schema_ready": True} for name, fields in schemas.items()},
        "candidate_only_default": True,
        "not_actual_flow_warning_required": True,
    }
    write_json(CONFIG_ROOT / "fund_etf_taxonomy.json", taxonomy)
    write_json(RUNTIME_ROOT / "fund_etf_schema_summary.json", summary)
    write_text(
        DOCS_ROOT / "FUND_ETF_CAPITAL_FLOW_DATA_MODEL_V1.md",
        """# Fund / ETF / Capital Flow Data Model v1

This model separates fund master data, ETF market data, holdings, and flow proxy observations.

Flow proxy fields such as ETF turnover, volume, AUM change, NAV change, shares outstanding change and holdings change must not be described as actual net fund flow unless the source field explicitly measures flow.

All datasets enter FR as candidate/staging evidence. Morningstar remains a licensed source candidate. China fund coverage requires official or authoritative source cross-checks before any trust upgrade.
""",
    )
    return summary


TEMPLATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "china_public_fund_official_list_template.csv": {
        "required": ["source_id", "source_name", "official_or_third_party", "fund_code", "fund_name", "publish_date"],
        "fields": [
            "source_id",
            "source_name",
            "official_or_third_party",
            "fund_code",
            "fund_name",
            "fund_type",
            "fund_company",
            "domicile",
            "market",
            "currency",
            "isin",
            "ticker",
            "exchange",
            "publish_date",
            "disclosure_date",
            "source_url",
            "review_note",
        ],
    },
    "fund_company_product_list_template.csv": {
        "required": ["source_id", "source_name", "fund_company", "fund_code", "fund_name", "publish_date"],
        "fields": [
            "source_id",
            "source_name",
            "official_or_third_party",
            "fund_company",
            "fund_code",
            "fund_name",
            "fund_type",
            "category",
            "currency",
            "isin",
            "publish_date",
            "source_url",
            "review_note",
        ],
    },
    "exchange_etf_list_template.csv": {
        "required": ["source_id", "source_name", "exchange", "etf_code", "etf_name", "publish_date"],
        "fields": [
            "source_id",
            "source_name",
            "official_or_third_party",
            "exchange",
            "etf_code",
            "etf_name",
            "fund_company",
            "asset_class",
            "currency",
            "listing_date",
            "publish_date",
            "source_url",
            "review_note",
        ],
    },
    "fund_holdings_template.csv": {
        "required": ["source_id", "fund_id", "holding_date", "holding_name", "weight", "publish_date"],
        "fields": [
            "source_id",
            "source_name",
            "official_or_third_party",
            "fund_id",
            "fund_code",
            "holding_date",
            "holding_name",
            "holding_code",
            "holding_identifier",
            "asset_type",
            "weight",
            "shares",
            "market_value",
            "sector",
            "country",
            "currency",
            "publish_date",
            "source_url",
            "review_note",
        ],
    },
}


def generate_manual_import_templates() -> dict[str, Any]:
    template_outputs = []
    for filename, spec in TEMPLATE_DEFINITIONS.items():
        rows = [{field: "" for field in spec["fields"]}]
        rows[0]["source_id"] = "fill_source_id"
        rows[0]["source_name"] = "fill_source_name"
        rows[0]["official_or_third_party"] = "official"
        write_csv(TEMPLATE_ROOT / filename, rows, spec["fields"])
        template_outputs.append(
            {
                "template_name": filename,
                "path": str(TEMPLATE_ROOT / filename),
                "required_fields": spec["required"],
                "fields": spec["fields"],
            }
        )
    guide = {
        "generated_at": utc_now(),
        "templates": template_outputs,
        "raw_manual_import_root": str(RUNTIME_ROOT / "raw" / "manual_imports"),
        "structured_output_root": str(RUNTIME_ROOT / "structured" / "fund_etf"),
        "manual_import_data_is_candidate": True,
    }
    write_json(RUNTIME_ROOT / "manual_import_framework.json", guide)
    write_text(
        DOCS_ROOT / "FUND_ETF_MANUAL_IMPORT_GUIDE.md",
        """# Fund / ETF Manual Import Guide

Use these templates for official or authoritative fund lists, issuer product lists, exchange ETF lists, and holdings files.

Manual imports must include source identity, official/third-party classification, publish/disclosure date, and source URL where available. Manual imports are not automatically trusted; they enter candidate/staging with quality checks and can be used for Morningstar cross-source coverage validation.

CLI:

```powershell
D:\\workspace\\envs\\financial_research_backend\\Scripts\\python.exe scripts\\run_fund_etf_manual_import.py validate --input <csv-path> --template china_public_fund_official_list_template.csv
```
""",
    )
    return guide


def load_morningstar_dataset_rows() -> list[dict[str, Any]]:
    audit = read_json(MORNINGSTAR_VALIDATION_ROOT / "global_fund_coverage_audit.json", default={})
    rows = audit.get("coverage_rows", [])
    return [row for row in rows if row.get("dataset_id")]


def build_matching_framework() -> dict[str, Any]:
    framework = {
        "generated_at": utc_now(),
        "matching_keys": ["fund_name", "fund_code", "isin", "ticker", "exchange", "fund_company", "category", "domicile", "currency"],
        "match_statuses": ["exact_match", "probable_match", "ambiguous_match", "no_match"],
        "score_rules": [
            {"rule": "ISIN exact", "score": 1.0},
            {"rule": "ticker + exchange exact", "score": 0.9},
            {"rule": "fund_code + fund_company exact", "score": 0.85},
            {"rule": "normalized name probable", "score": 0.65},
        ],
        "sample_mode": "schema_test_only_until_official_import_available",
        "sample_match_result": {
            "official_fund_id": "template_only",
            "official_fund_name": "Template Official Fund",
            "morningstar_sec_id": None,
            "morningstar_name": None,
            "match_method": "not_run_no_official_import",
            "match_score": 0,
            "match_status": "no_match",
            "fields_compared": [],
            "notes": "No real coverage is inferred from template data.",
        },
    }
    write_json(RUNTIME_ROOT / "morningstar_matching_framework.json", framework)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_FUND_MATCHING_FRAMEWORK.md",
        """# Morningstar Fund Matching Framework

Matching uses official fund records as the anchor and compares ISIN, ticker, exchange, fund code, fund company, category, domicile, currency and normalized names against Morningstar identifiers.

Template-only rows are only schema tests. They do not create real coverage metrics.
""",
    )
    return framework


def build_coverage_validation() -> dict[str, Any]:
    result = {
        "generated_at": utc_now(),
        "official_count": 0,
        "morningstar_candidate_count": len(load_morningstar_dataset_rows()),
        "matched_count": 0,
        "unmatched_official_count": 0,
        "unmatched_morningstar_count": None,
        "coverage_ratio": None,
        "field_completeness_score": None,
        "freshness_gap_days": None,
        "cross_source_match_rate": None,
        "trust_upgrade_status": "not_eligible_no_official_import",
        "quality_status": "needs_review",
        "manual_import_required": True,
        "rules": {
            "coverage_ratio_min": 0.9,
            "field_completeness_min": 0.95,
            "freshness_gap_days_max": 7,
            "cross_source_match_rate_min": 0.98,
        },
        "candidate_only": True,
    }
    write_json(RUNTIME_ROOT / "fund_coverage_validation_results.json", result)
    write_text(
        DOCS_ROOT / "FUND_ETF_COVERAGE_VALIDATION_RULES.md",
        """# Fund / ETF Coverage Validation Rules

Coverage validation compares official/authoritative fund lists against Morningstar matches. A dataset cannot be upgraded if coverage, freshness, field completeness, cross-source match, QA or license/storage checks fail.

No official import has been loaded yet, so coverage ratio is intentionally unavailable.
""",
    )
    return result


def priority_dataset_shortlist() -> dict[str, Any]:
    rows = load_morningstar_dataset_rows()
    priority_terms = [
        ("holdings", "Fund / ETF holdings"),
        ("portfolio", "Portfolio or holdings"),
        ("share class", "Fund / ETF master"),
        ("return", "Performance / NAV / returns"),
        ("performance", "Performance / NAV / returns"),
        ("rating", "Fund category / rating"),
        ("index", "Benchmark / index"),
        ("allocation", "Asset allocation"),
        ("exposure", "Sector/country exposure"),
    ]
    shortlisted = []
    for row in rows:
        name = clean_text(row.get("dataset_name") or "")
        lowered = name.lower()
        likely = None
        priority = 99
        for idx, (term, use_case) in enumerate(priority_terms, start=1):
            if term in lowered:
                likely = use_case
                priority = idx
                break
        if likely:
            shortlisted.append(
                {
                    "dataset_id": row.get("dataset_id"),
                    "dataset_name": name,
                    "likely_use_case": likely,
                    "entitlement_status": row.get("permission_status"),
                    "download_risk": "do_not_download_until_entitlement_and_license_review",
                    "raw_storage_risk": "needs_user_confirmation",
                    "freshness_unknown": True,
                    "priority": priority,
                    "next_test_action": "field metadata sample or user-approved tiny sample only",
                }
            )
    shortlisted = sorted(shortlisted, key=lambda item: (item["priority"], item["dataset_name"]))[:10]
    result = {
        "generated_at": utc_now(),
        "items": shortlisted,
        "large_download_performed": False,
        "candidate_only": True,
    }
    write_json(RUNTIME_ROOT / "morningstar_priority_dataset_shortlist.json", result)
    return result


def build_trust_upgrade_queue(shortlist: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    queue = []
    for item in shortlist.get("items", []):
        queue.append(
            {
                "dataset_id": item["dataset_id"],
                "source_id": "morningstar_direct",
                "current_status": "licensed_source_candidate",
                "required_checks": [
                    "entitlement_allowed",
                    "official_coverage_crosscheck",
                    "freshness_validation",
                    "field_completeness_validation",
                    "license_storage_boundary_confirmed",
                    "QA_quality_passed",
                ],
                "completed_checks": ["metadata_visible"],
                "blockers": [
                    "official_import_missing",
                    "freshness_unknown",
                    "field_completeness_unknown",
                    "license_storage_boundary_needs_review",
                ],
                "next_action": item["next_test_action"],
                "can_upgrade_to_trusted_candidate": False,
            }
        )
    result = {
        "generated_at": utc_now(),
        "trusted_candidate_count": 0,
        "queue": queue,
        "coverage_validation_status": coverage["trust_upgrade_status"],
        "formal_trusted_consumption": False,
    }
    write_json(RUNTIME_ROOT / "trust_upgrade_queue.json", result)
    return result


def update_dashboard_status(shortlist: dict[str, Any], coverage: dict[str, Any], trust_queue: dict[str, Any]) -> None:
    dashboard = read_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", default={"sources": []})
    sources = [source for source in dashboard.get("sources", []) if source.get("source_id") != "fund_etf_capital_flow_foundation"]
    sources.append(
        {
            "source_id": "fund_etf_capital_flow_foundation",
            "display_name": "Fund & ETF Capital Flow Foundation",
            "status": "manual_import_ready",
            "official_import_available": False,
            "morningstar_matching_framework_ready": True,
            "coverage_validation_status": coverage["trust_upgrade_status"],
            "priority_dataset_count": len(shortlist.get("items", [])),
            "trust_upgrade_queue_count": len(trust_queue.get("queue", [])),
            "trusted_candidate_count": trust_queue["trusted_candidate_count"],
            "warning": "Flow proxy is not actual flow. Official China fund import is required before Morningstar coverage validation.",
            "candidate_only": True,
        }
    )
    write_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", {"generated_at": utc_now(), "sources": sources})


def write_summary(
    schema_summary: dict[str, Any],
    manual: dict[str, Any],
    matching: dict[str, Any],
    coverage: dict[str, Any],
    shortlist: dict[str, Any],
    trust_queue: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "generated_at": utc_now(),
        "fund_etf_capital_flow_foundation_completed": True,
        "data_model_completed": True,
        "manual_import_framework_completed": True,
        "import_templates": [item["template_name"] for item in manual["templates"]],
        "morningstar_matching_framework_completed": True,
        "coverage_validation_pipeline_completed": True,
        "morningstar_priority_dataset_count": len(shortlist["items"]),
        "trust_upgrade_queue_count": len(trust_queue["queue"]),
        "trusted_candidate_count": trust_queue["trusted_candidate_count"],
        "large_download_performed": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "outputs": {
            "schema_summary": str(RUNTIME_ROOT / "fund_etf_schema_summary.json"),
            "manual_import_templates": str(TEMPLATE_ROOT),
            "matching_framework": str(RUNTIME_ROOT / "morningstar_matching_framework.json"),
            "coverage_validation": str(RUNTIME_ROOT / "fund_coverage_validation_results.json"),
            "priority_dataset_shortlist": str(RUNTIME_ROOT / "morningstar_priority_dataset_shortlist.json"),
            "trust_upgrade_queue": str(RUNTIME_ROOT / "trust_upgrade_queue.json"),
        },
    }
    write_json(RUNTIME_ROOT / "fund_etf_capital_flow_summary.json", summary)
    return summary


def run() -> dict[str, Any]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    schema_summary = write_data_model()
    manual = generate_manual_import_templates()
    matching = build_matching_framework()
    coverage = build_coverage_validation()
    shortlist = priority_dataset_shortlist()
    trust_queue = build_trust_upgrade_queue(shortlist, coverage)
    update_dashboard_status(shortlist, coverage, trust_queue)
    return write_summary(schema_summary, manual, matching, coverage, shortlist, trust_queue)


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "completed": result["fund_etf_capital_flow_foundation_completed"],
                "templates": result["import_templates"],
                "priority_dataset_count": result["morningstar_priority_dataset_count"],
                "trusted_candidate_count": result["trusted_candidate_count"],
                "outputs_root": str(RUNTIME_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
