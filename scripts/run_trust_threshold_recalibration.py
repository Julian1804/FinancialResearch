from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_automated_ingestion_v1 import CONFIG_ROOT, DOCS_ROOT, RUNTIME_ROOT, read_json, write_json, write_text  # noqa: E402


OUTPUT_ROOT = RUNTIME_ROOT / "trust_threshold_recalibration"
V4_ROOT = RUNTIME_ROOT / "v4_trust_closure"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_recalibration() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    policy = update_institutional_policy()
    promotion = update_promotion_rules()
    trust_rules = update_trust_rules()
    interface_map = build_akshare_interface_classification()
    a_share = recalibrate_a_share_etf(interface_map)
    dashboard = update_dashboard(policy, interface_map, a_share)
    docs = write_docs(policy, interface_map, a_share)
    summary = {
        "generated_at": utc_now(),
        "trust_threshold_recalibration_completed": True,
        "trusted_threshold_lowered": True,
        "institutional_proxy_source_completed": True,
        "new_status": "institutional_proxy_high_confidence_candidate",
        "akshare_baostock_strategy": a_share["strategy_summary"],
        "a_share_etf_upgrade": a_share["summary"],
        "eastmoney_backed_deferred_preserved": True,
        "dashboard_updated": True,
        "formal_trusted_consumption_affected": False,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "outputs": {
            "policy": str(CONFIG_ROOT / "institutional_data_source_trust_policy.json"),
            "candidate_promotion_rules": str(CONFIG_ROOT / "candidate_promotion_rules.json"),
            "trust_closure_rules": str(CONFIG_ROOT / "trust_closure_rules_v4.json"),
            "akshare_interface_classification": str(CONFIG_ROOT / "akshare_interface_trust_classification.json"),
            "a_share_recalibration": str(OUTPUT_ROOT / "a_share_etf_trust_recalibration_result.json"),
            "dashboard_status": str(RUNTIME_ROOT / "dashboard_automation_status_trust_recalibration.json"),
            "docs": docs,
        },
    }
    write_json(OUTPUT_ROOT / "trust_threshold_recalibration_summary.json", summary)
    return summary


def update_institutional_policy() -> dict[str, Any]:
    policy = read_json(CONFIG_ROOT / "institutional_data_source_trust_policy.json", {})
    source_types = policy.setdefault("source_type_taxonomy", [])
    if "institutional_proxy_source" not in source_types:
        source_types.insert(3, "institutional_proxy_source")
    state_policy = policy.setdefault("candidate_state_policy", {})
    state_policy["institutional_proxy_high_confidence_candidate"] = (
        "Interface-level wrapper/proxy data whose upstream provenance is a mature institutional market data, exchange, or official source; "
        "requires stable endpoint, QA pass, clear entity mapping, and field-level provenance."
    )
    state_policy["trusted_candidate"] = (
        "For official, institutional, licensed institutional, or institutional proxy source lines, trusted_candidate can be assigned at dataset/field level "
        "when provenance is explicit, QA passes, entity mapping is clear, and logic checks pass. Coverage need not be 100%."
    )
    policy["version"] = "institutional_data_source_trust_policy_v2_proxy_recalibration"
    policy["generated_at"] = utc_now()
    policy["institutional_proxy_source_policy"] = {
        "not_blanket_wrapper_trust": True,
        "trust_inherited_from_upstream": True,
        "requires_interface_level_classification": True,
        "can_reach_trusted_candidate_without_coverage_100_percent": True,
        "required_evidence": [
            "upstream_provenance",
            "endpoint_stability",
            "QA passed",
            "entity mapping clear",
            "field-level completeness or explicit field limitation",
            "no deferred/unstable endpoint",
        ],
        "blocked_when": [
            "upstream_unknown",
            "endpoint_unstable",
            "QA failed",
            "entity unresolved",
            "fields abnormal or severe warning",
        ],
    }
    write_json(CONFIG_ROOT / "institutional_data_source_trust_policy.json", policy)
    return policy


def update_promotion_rules() -> dict[str, Any]:
    rules = read_json(CONFIG_ROOT / "candidate_promotion_rules.json", {})
    states = rules.setdefault("states", [])
    existing = {state.get("status") for state in states}
    if "institutional_proxy_high_confidence_candidate" not in existing:
        states.append(
            {
                "status": "institutional_proxy_high_confidence_candidate",
                "conditions": [
                    "interface-level upstream provenance points to institutional/official/exchange market data",
                    "endpoint stable for controlled runs",
                    "QA and entity mapping pass",
                    "field limitations explicitly labeled",
                ],
                "evidence_required": [
                    "interface trust classification",
                    "QA report",
                    "entity mapping",
                    "field coverage matrix",
                ],
                "downgrade_conditions": [
                    "upstream provenance unknown",
                    "endpoint deferred or unstable",
                    "QA failed",
                    "severe field warning",
                ],
            }
        )
    for state in states:
        if state.get("status") == "trusted_candidate":
            state["conditions"] = [
                "official/institutional/licensed/institutional-proxy source line has explicit provenance",
                "QA passes and entity mapping is clear",
                "field-level logic checks pass",
                "coverage limitations are labeled and do not block dataset/field-level trust",
                "formal trusted consumption remains off",
            ]
            state["evidence_required"] = [
                "source or upstream provenance",
                "automated QA report",
                "entity crosswalk result",
                "field-level upgrade scope",
            ]
    rules["version"] = "candidate_promotion_rules_v3_proxy_recalibration"
    rules["generated_at"] = utc_now()
    rules["trusted_threshold_recalibration"] = {
        "coverage_100_percent_not_required": True,
        "applies_to": ["official_source", "institutional_database", "licensed_institutional_source", "institutional_proxy_source"],
        "formal_trusted_consumption_unchanged": True,
    }
    write_json(CONFIG_ROOT / "candidate_promotion_rules.json", rules)
    return rules


def update_trust_rules() -> dict[str, Any]:
    rules = read_json(CONFIG_ROOT / "trust_closure_rules_v4.json", {})
    states = rules.setdefault("states", [])
    existing = {state.get("status") for state in states}
    if "institutional_proxy_high_confidence_candidate" not in existing:
        states.append(
            {
                "status": "institutional_proxy_high_confidence_candidate",
                "conditions": [
                    "wrapper/proxy interface inherits confidence from explicit upstream institutional or official source",
                    "interface is stable and QA/entity mapping pass",
                ],
                "evidence_required": ["upstream provenance", "controlled run QA", "field-level coverage"],
                "downgrade_conditions": ["deferred endpoint", "unknown upstream", "QA failure"],
            }
        )
    rules["version"] = "trust_closure_rules_v6_proxy_recalibration"
    rules["generated_at"] = utc_now()
    rules["proxy_recalibration"] = {
        "threshold_lowered_for_institutional_proxy": True,
        "trusted_candidate_allowed_at_field_or_dataset_level": True,
        "formal_trusted_consumption_unchanged": True,
    }
    write_json(CONFIG_ROOT / "trust_closure_rules_v4.json", rules)
    return rules


def build_akshare_interface_classification() -> dict[str, Any]:
    payload = {
        "version": "akshare_interface_trust_classification_v1",
        "generated_at": utc_now(),
        "principle": "AKShare is a wrapper; trust is assigned at interface level from explicit upstream provenance, not to the whole package.",
        "interfaces": [
            {
                "interface_id": "akshare_tencent_daily",
                "wrapper": "AKShare",
                "upstream": "Tencent market data endpoint",
                "source_type": "institutional_proxy_source",
                "upstream_role": "mature_institutional_market_data_provider",
                "endpoint_status": "stable_in_controlled_v4_run",
                "qa_status": "quality_passed_for_price_fields",
                "field_limitations": ["amount_missing", "turnover_rate_missing", "some derived fields unavailable"],
                "trust_status": "institutional_proxy_high_confidence_candidate",
                "trusted_scope": "A-share/ETF OHLC price fields when cross-validated with Baostock",
            },
            {
                "interface_id": "baostock_daily",
                "wrapper": "Baostock",
                "upstream": "Baostock A-share historical data service",
                "source_type": "open_source_api_wrapper",
                "upstream_role": "operational_market_data_service",
                "endpoint_status": "stable_in_controlled_v4_run",
                "qa_status": "quality_passed",
                "field_limitations": [],
                "trust_status": "production_candidate_and_cross_validation_partner",
                "trusted_scope": "A-share/ETF OHLCV fields after cross-source validation; not a blanket official source",
            },
            {
                "interface_id": "akshare_eastmoney_stock_zh_a_hist",
                "wrapper": "AKShare",
                "upstream": "Eastmoney push2his",
                "source_type": "institutional_proxy_source",
                "upstream_role": "institutional_database_public_endpoint",
                "endpoint_status": "deferred_unstable",
                "qa_status": "not_currently_usable",
                "field_limitations": ["TLS/upstream disconnect", "empty response risk"],
                "trust_status": "deferred",
                "trusted_scope": "none_until_endpoint_stability_recovers",
            },
            {
                "interface_id": "akshare_unknown_or_unclassified",
                "wrapper": "AKShare",
                "upstream": "unknown",
                "source_type": "open_source_api_wrapper",
                "upstream_role": "unknown",
                "endpoint_status": "requires_interface_audit",
                "qa_status": "not_evaluated",
                "field_limitations": ["upstream_unknown"],
                "trust_status": "candidate_only",
                "trusted_scope": "none",
            },
        ],
    }
    write_json(CONFIG_ROOT / "akshare_interface_trust_classification.json", payload)
    return payload


def recalibrate_a_share_etf(interface_map: dict[str, Any]) -> dict[str, Any]:
    v4 = read_json(V4_ROOT / "a_share_etf_trust_closure_results.json", {})
    summary = v4.get("summary", {})
    field_counts = summary.get("field_status_counts", {})
    common_records = int(summary.get("common_records") or 0)
    mismatch_count = int(summary.get("mismatch_count") or 0)
    exact_match = int(field_counts.get("exact_match") or 0)
    expected_ohlc = common_records * 4
    ohlc_pass = common_records > 0 and mismatch_count == 0 and exact_match >= expected_ohlc
    akshare_tencent = next(item for item in interface_map["interfaces"] if item["interface_id"] == "akshare_tencent_daily")
    eastmoney = next(item for item in interface_map["interfaces"] if item["interface_id"] == "akshare_eastmoney_stock_zh_a_hist")
    trusted_candidate_scope = []
    ready_scope = []
    blockers = []
    if ohlc_pass and akshare_tencent["trust_status"] == "institutional_proxy_high_confidence_candidate":
        trusted_candidate_scope.append("A-share/ETF OHLC price fields for 16-symbol controlled watchlist")
        ready_scope.append("A-share/ETF daily market dataset excluding unsupported secondary fields")
    if field_counts.get("missing_in_secondary"):
        blockers.append("AKShare Tencent secondary source does not cover amount/turnover/pct_change/preclose consistently in current normalized sample")
    result = {
        "generated_at": utc_now(),
        "strategy_summary": {
            "akshare_package_blanket_trust": False,
            "interface_level_trust": True,
            "akshare_tencent": "institutional_proxy_high_confidence_candidate",
            "baostock": "production_candidate_and_cross_validation_partner",
            "eastmoney_backed": eastmoney["trust_status"],
            "formal_trusted_consumption": False,
        },
        "summary": {
            "input_common_records": common_records,
            "mismatch_count": mismatch_count,
            "ohlc_exact_match_count": exact_match,
            "expected_ohlc_match_count": expected_ohlc,
            "ohlc_pass": ohlc_pass,
            "trusted_candidate_assigned": bool(trusted_candidate_scope),
            "ready_for_trusted_candidate_assigned": bool(ready_scope),
            "trusted_candidate_scope": trusted_candidate_scope,
            "ready_for_trusted_candidate_scope": ready_scope,
            "blocked_or_limited_scope": blockers,
            "candidate_only": True,
            "formal_trusted_consumption": False,
        },
        "evidence": {
            "source_mode": summary.get("source_mode"),
            "requested_total": summary.get("requested_total"),
            "baostock_records": summary.get("baostock_records"),
            "akshare_tencent_records": summary.get("akshare_tencent_records"),
            "field_status_counts": field_counts,
            "fetch_errors": v4.get("fetch_errors"),
            "raw_paths": v4.get("raw_paths"),
            "normalized_paths": v4.get("normalized_paths"),
        },
    }
    write_json(OUTPUT_ROOT / "a_share_etf_trust_recalibration_result.json", result)
    return result


def update_dashboard(policy: dict[str, Any], interface_map: dict[str, Any], a_share: dict[str, Any]) -> dict[str, Any]:
    status = read_json(RUNTIME_ROOT / "dashboard_automation_status.json", {})
    panel = {
        "generated_at": utc_now(),
        "title": "Trust Threshold Recalibration",
        "trusted_threshold_lowered": True,
        "institutional_proxy_source_completed": True,
        "institutional_proxy_high_confidence_candidate": True,
        "a_share_etf": a_share["summary"],
        "akshare_interface_classification": {
            item["interface_id"]: item["trust_status"] for item in interface_map["interfaces"]
        },
        "eastmoney_backed_deferred_preserved": True,
        "formal_trusted_consumption_affected": False,
        "no_openai_api_called": True,
    }
    status["trust_threshold_recalibration"] = panel
    write_json(RUNTIME_ROOT / "dashboard_automation_status_trust_recalibration.json", panel)
    write_json(RUNTIME_ROOT / "dashboard_automation_status.json", status)
    return panel


def write_docs(policy: dict[str, Any], interface_map: dict[str, Any], a_share: dict[str, Any]) -> dict[str, str]:
    docs = {
        "policy": str(DOCS_ROOT / "TRUST_THRESHOLD_RECALIBRATION_POLICY.md"),
        "akshare": str(DOCS_ROOT / "AKSHARE_INTERFACE_LEVEL_TRUST_CLASSIFICATION.md"),
        "a_share": str(DOCS_ROOT / "A_SHARE_ETF_TRUST_RECALIBRATION_RESULT.md"),
    }
    write_text(
        Path(docs["policy"]),
        f"""# Trust Threshold Recalibration Policy

Generated: {utc_now()}

Trusted thresholds are recalibrated for institutional databases and institutional proxy sources. Coverage does not need to be 100% for a field-level or dataset-level `trusted_candidate` assignment when upstream provenance is clear, QA passes, entity mapping is clear, and field logic checks pass.

Formal trusted consumption remains off.
""",
    )
    write_text(
        Path(docs["akshare"]),
        f"""# AKShare Interface-Level Trust Classification

Generated: {utc_now()}

AKShare is a wrapper, not a single data source. Trust is classified per interface:

{chr(10).join(f"- `{item['interface_id']}`: {item['trust_status']} ({item['upstream']})" for item in interface_map['interfaces'])}
""",
    )
    write_text(
        Path(docs["a_share"]),
        f"""# A-share / ETF Trust Recalibration Result

Generated: {utc_now()}

Common records: {a_share['summary']['input_common_records']}
Mismatch count: {a_share['summary']['mismatch_count']}
Trusted candidate assigned: {a_share['summary']['trusted_candidate_assigned']}
Trusted scope: {a_share['summary']['trusted_candidate_scope']}

Full formal trusted consumption remains unchanged.
""",
    )
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalibrate trust thresholds for institutional proxy sources.")
    parser.parse_args()
    summary = run_recalibration()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
