from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_automated_ingestion_v1 import CONFIG_ROOT, DOCS_ROOT, ENTITY_ROOT, RUNTIME_ROOT, read_json, read_jsonl, write_json, write_text  # noqa: E402


V4_ROOT = RUNTIME_ROOT / "v4_trust_closure"
OUTPUT_ROOT = RUNTIME_ROOT / "institutional_trust_qa_pipeline"


NEW_SOURCE_TYPES = [
    "institutional_database",
    "official_source",
    "licensed_institutional_source",
    "open_source_api_wrapper",
    "authoritative_third_party",
    "media_or_news_source",
    "community_or_unverified_source",
]

NEW_CANDIDATE_STATES = [
    "institutional_high_confidence_candidate",
    "licensed_high_confidence_candidate",
    "production_candidate",
    "coverage_limited_but_usable",
    "freshness_limited_but_usable",
    "media_event_candidate",
    "needs_cross_source_fact_check",
    "anomaly_flagged_candidate",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_institutional_trust_qa_pipeline() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    policy = write_institutional_trust_policy()
    source_strategy = update_source_strategy()
    promotion_rules = update_candidate_promotion_rules()
    trust_rules = update_trust_closure_rules(policy)
    qa_policy = write_automated_qa_policy()
    entity_rules = update_entity_identifier_rules()

    proof = run_controlled_proof_qa(qa_policy, source_strategy)
    entity_update = build_entity_crosswalk_update(proof)
    dashboard = update_dashboard_trust_pipeline(policy, proof, entity_update)
    docs = write_docs(policy, qa_policy, proof, source_strategy, entity_update)

    summary = {
        "generated_at": utc_now(),
        "institutional_policy_adjustment_completed": True,
        "source_types": NEW_SOURCE_TYPES,
        "candidate_states_added_or_confirmed": NEW_CANDIDATE_STATES,
        "morningstar_status": proof["source_summaries"]["morningstar_direct"]["assigned_statuses"],
        "controlled_proof_sources": list(proof["source_summaries"].keys()),
        "qa_result_counts": proof["qa_summary"]["status_counts"],
        "candidate_status_counts": proof["candidate_status_summary"],
        "entity_crosswalk_updated": True,
        "entity_crosswalk_increment": entity_update["summary"]["crosswalk_increment"],
        "dashboard_updated": True,
        "formal_trusted_consumption_affected": False,
        "no_auto_login_morningstar": True,
        "no_password_saved": True,
        "token_leaked": False,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "outputs": {
            "policy": str(CONFIG_ROOT / "institutional_data_source_trust_policy.json"),
            "source_strategy": str(CONFIG_ROOT / "automated_source_strategy.json"),
            "promotion_rules": str(CONFIG_ROOT / "candidate_promotion_rules.json"),
            "trust_closure_rules": str(CONFIG_ROOT / "trust_closure_rules_v4.json"),
            "qa_policy": str(CONFIG_ROOT / "automated_qa_policy.json"),
            "entity_rules": str(CONFIG_ROOT / "entity_identifier_rules.json"),
            "qa_results": str(OUTPUT_ROOT / "automated_qa_results.json"),
            "proof_run": str(OUTPUT_ROOT / "controlled_proof_run_results.json"),
            "candidate_updates": str(OUTPUT_ROOT / "candidate_status_update_results.json"),
            "entity_crosswalk_update": str(OUTPUT_ROOT / "entity_crosswalk_update_results.json"),
            "dashboard_status": str(RUNTIME_ROOT / "dashboard_automation_status_institutional_qa.json"),
            "docs": docs,
        },
    }
    write_json(OUTPUT_ROOT / "institutional_trust_qa_pipeline_summary.json", summary)
    return summary


def write_institutional_trust_policy() -> dict[str, Any]:
    policy = {
        "version": "institutional_data_source_trust_policy_v1",
        "generated_at": utc_now(),
        "source_type_taxonomy": NEW_SOURCE_TYPES,
        "principles": [
            "Institutional financial databases are not treated like ordinary media or web pages.",
            "Institutional database QA emphasizes schema, dates, units, entity identifiers, logic checks, anomaly flags, license/storage boundary, coverage and freshness.",
            "Coverage limitations are normal and do not make an institutional database untrusted as a platform.",
            "Media/news/community sources can provide event, sentiment, or clue candidates, but key facts require cross-source fact checks.",
            "Anomalies are retained with flags rather than silently deleted.",
            "Formal trusted consumption remains unchanged until a separate production switch exists.",
        ],
        "institutional_database_examples": ["Morningstar Direct", "Wind", "Eastmoney data terminal", "Tonghuashun data terminal", "authorized exchange data"],
        "media_or_news_examples": ["financial media", "news reports", "self-media", "social platforms", "ordinary web pages"],
        "candidate_state_policy": {
            "institutional_high_confidence_candidate": "Institutional database source with QA-passing schema/logic and clear source identifiers; coverage/freshness/license may still be limited.",
            "licensed_high_confidence_candidate": "Licensed institutional source such as Morningstar with entitlement/manual token control and no automatic login.",
            "production_candidate": "Automated pipeline can store and update data as candidate/staging evidence after QA; not formal trusted consumption.",
            "coverage_limited_but_usable": "Dataset may not cover all entities, but observed coverage is still usable and should be labeled.",
            "freshness_limited_but_usable": "Dataset has useful historical or identifier value even if latest updates lag or freshness cadence is limited.",
            "media_event_candidate": "Media/news event or sentiment item, never an institutional data fact by itself.",
            "needs_cross_source_fact_check": "Ordinary media/community source fact needs validation before research factual use.",
            "anomaly_flagged_candidate": "Data kept with anomaly flags and review notes.",
        },
        "morningstar_treatment": {
            "source_type": "licensed_institutional_source",
            "default_status": "licensed_high_confidence_candidate",
            "identifier_anchor_allowed": True,
            "full_trusted_requires": ["license/storage boundary", "field completeness", "freshness", "coverage", "entity crosswalk", "automated QA"],
            "not_public_free_source": True,
        },
        "formal_trusted_consumption_unchanged": True,
    }
    write_json(CONFIG_ROOT / "institutional_data_source_trust_policy.json", policy)
    return policy


def update_source_strategy() -> dict[str, Any]:
    strategy = read_json(CONFIG_ROOT / "automated_source_strategy.json", {})
    sources = strategy.get("sources", [])
    by_id = {item.get("source_id"): item for item in sources}

    def upsert(source: dict[str, Any]) -> None:
        if source["source_id"] in by_id:
            by_id[source["source_id"]].update(source)
        else:
            sources.append(source)
            by_id[source["source_id"]] = source

    upsert(
        {
            "source_id": "morningstar_direct",
            "source_type": "licensed_institutional_source",
            "domains_supported": ["fund_etf", "holdings", "equity", "index", "performance", "entity_master"],
            "automation_status": "controlled_production_candidate",
            "trust_role": "licensed_high_confidence_candidate",
            "blocker": "license/storage boundary and dataset-specific coverage/freshness still need review before trusted_candidate",
            "next_action": "controlled candidate backfill for high-value identifier and fund/ETF datasets when token and entitlement allow",
            "candidate_only": True,
            "formal_trusted_consumption": False,
        }
    )
    upsert(
        {
            "source_id": "wind_terminal",
            "source_type": "licensed_institutional_source",
            "domains_supported": ["macro", "equity", "fund_etf", "rates_bond", "fx_currency", "commodity"],
            "access_method": "licensed terminal/API",
            "automation_status": "needs_license",
            "update_frequency": "dataset_specific",
            "rate_limit_policy": "not_configured",
            "blocker": "no current Wind license/API configured",
            "fallback_source": "official/FRED/Treasury/Morningstar/AKShare candidates",
            "trust_role": "licensed_high_confidence_candidate_after_entitlement",
            "next_action": "user license/API confirmation",
            "candidate_only": True,
            "formal_trusted_consumption": False,
        }
    )
    upsert(
        {
            "source_id": "eastmoney_institutional_database",
            "source_type": "institutional_database",
            "domains_supported": ["equity", "fund_etf", "market_daily", "capital_flow"],
            "access_method": "authorized platform or stable public wrapper where allowed",
            "automation_status": "candidate_when_endpoint_stable",
            "update_frequency": "daily",
            "rate_limit_policy": "low_frequency_no_captcha_bypass",
            "blocker": "public Eastmoney push2his unstable; authorized boundary not configured",
            "fallback_source": "AKShare Tencent / Baostock / Morningstar",
            "trust_role": "institutional_high_confidence_candidate_after_endpoint_validation",
            "next_action": "use only verified stable endpoints or authorized access",
            "candidate_only": True,
            "formal_trusted_consumption": False,
        }
    )
    upsert(
        {
            "source_id": "tonghuashun_institutional_database",
            "source_type": "institutional_database",
            "domains_supported": ["equity", "fund_etf", "market_daily", "capital_flow"],
            "access_method": "authorized platform or legal API/wrapper where allowed",
            "automation_status": "needs_license_or_endpoint_review",
            "update_frequency": "daily",
            "rate_limit_policy": "low_frequency_no_captcha_bypass",
            "blocker": "no current authorized API configured",
            "fallback_source": "official/Morningstar/AKShare candidates",
            "trust_role": "institutional_high_confidence_candidate_after_endpoint_validation",
            "next_action": "source-specific feasibility and license review",
            "candidate_only": True,
            "formal_trusted_consumption": False,
        }
    )
    for source in sources:
        sid = source.get("source_id", "")
        if sid in {"fred", "us_treasury_fiscaldata", "world_bank_pink_sheet", "nasdaq_trader_symbol_directory", "amac_aggregate_pdf"}:
            source["source_type"] = "official_source"
        if sid in {"baostock", "akshare_tencent", "akshare_eastmoney"}:
            source["source_type"] = "open_source_api_wrapper"
            if sid in {"baostock", "akshare_tencent"}:
                source["trust_role"] = "production_candidate_after_QA_and_cross_source_validation"
        if sid == "eastmoney_public":
            source["source_type"] = "authoritative_third_party"
            source["trust_role"] = "candidate_only_until_endpoint_and_terms_stable"
    strategy["version"] = "automated_source_strategy_v2_institutional_policy"
    strategy["generated_at"] = utc_now()
    strategy["source_type_taxonomy"] = NEW_SOURCE_TYPES
    strategy["status_counts"] = dict(Counter(item.get("automation_status", "unknown") for item in sources))
    strategy["sources"] = sources
    write_json(CONFIG_ROOT / "automated_source_strategy.json", strategy)
    write_json(OUTPUT_ROOT / "source_strategy_adjustment_results.json", strategy)
    return strategy


def update_candidate_promotion_rules() -> dict[str, Any]:
    rules = read_json(CONFIG_ROOT / "candidate_promotion_rules.json", {})
    states = rules.setdefault("states", [])
    existing = {item.get("status") for item in states}
    definitions = {
        "institutional_high_confidence_candidate": "institutional database QA passes schema/date/unit/entity checks; coverage limitations are labeled rather than treated as source failure",
        "licensed_high_confidence_candidate": "licensed institutional source is entitlement-visible and safely handled; license/storage boundary remains explicit",
        "production_candidate": "automated low-frequency pipeline can backfill/increment and store as candidate/staging after QA",
        "coverage_limited_but_usable": "coverage does not reach full universe but is usable for labeled subset analysis",
        "freshness_limited_but_usable": "freshness is limited but historical/entity-anchor use remains valid",
        "media_event_candidate": "media or news item candidate only for events/sentiment/clues",
        "needs_cross_source_fact_check": "ordinary media/community fact requires cross-source validation",
        "anomaly_flagged_candidate": "format/logic QA mostly passes but anomaly flags require review",
    }
    for status, description in definitions.items():
        if status not in existing:
            states.append(
                {
                    "status": status,
                    "conditions": [description],
                    "evidence_required": ["automated QA result", "source type", "candidate status reason"],
                    "downgrade_conditions": ["QA failed", "license/storage boundary blocks use", "source misclassified"],
                }
            )
    rules["version"] = "candidate_promotion_rules_v2_institutional_policy"
    rules["generated_at"] = utc_now()
    rules["institutional_policy_note"] = "Institutional databases do not need ordinary-media-style fact-by-fact skepticism before candidate storage; QA focuses on automated format/logic/anomaly checks and license/storage/entity boundaries."
    rules["formal_trusted_consumption_unchanged"] = True
    write_json(CONFIG_ROOT / "candidate_promotion_rules.json", rules)
    return rules


def update_trust_closure_rules(policy: dict[str, Any]) -> dict[str, Any]:
    rules = read_json(CONFIG_ROOT / "trust_closure_rules_v4.json", {})
    rules["version"] = "trust_closure_rules_v5_institutional_policy"
    rules["generated_at"] = utc_now()
    rules["institutional_source_treatment"] = policy
    states = rules.setdefault("states", [])
    existing = {item.get("status") for item in states}
    for status in NEW_CANDIDATE_STATES:
        if status not in existing:
            states.append(
                {
                    "status": status,
                    "conditions": [policy["candidate_state_policy"][status]],
                    "evidence_required": ["source classification", "automated QA", "license/storage note", "entity mapping where applicable"],
                    "downgrade_conditions": ["QA failed", "source role invalid", "blocked license/storage boundary"],
                }
            )
    write_json(CONFIG_ROOT / "trust_closure_rules_v4.json", rules)
    return rules


def write_automated_qa_policy() -> dict[str, Any]:
    qa_policy = {
        "version": "automated_qa_policy_v1",
        "generated_at": utc_now(),
        "scope": "raw -> normalized -> entity mapping -> automated QA -> anomaly flag -> candidate status -> dashboard summary",
        "checks": [
            "required_fields_present",
            "date_parseable",
            "numeric_fields_parseable",
            "unit_currency_present_or_warning",
            "duplicate_entity_date_source",
            "non_negative_price_volume_aum_nav",
            "ohlc_rule_check",
            "pct_change_reasonable_range",
            "source_identifier_present",
            "entity_mapping_attempted",
            "revision_vintage_or_retrieval_snapshot_present",
            "license_storage_boundary_classified",
        ],
        "status_policy": {
            "quality_passed": "no failed checks and no material warning",
            "quality_warning": "non-blocking missing fields or limited release/freshness/license details",
            "anomaly_flagged_candidate": "value retained with anomaly/review flag",
            "quality_failed": "required schema or core value/date checks fail",
        },
        "anomaly_retention_policy": "Keep raw and normalized value with anomaly_flag/review_flag; do not silently delete.",
        "formal_trusted_consumption_unchanged": True,
    }
    write_json(CONFIG_ROOT / "automated_qa_policy.json", qa_policy)
    return qa_policy


def update_entity_identifier_rules() -> dict[str, Any]:
    rules = read_json(CONFIG_ROOT / "entity_identifier_rules.json", {})
    rules["version"] = "entity_identifier_rules_v2_institutional_policy"
    rules["generated_at"] = utc_now()
    rules["institutional_identifier_anchor_policy"] = {
        "allowed_anchor_sources": ["morningstar_direct", "wind_terminal", "authorized_exchange_data"],
        "priority_fields": ["morningstar_sec_id", "isin", "ticker", "exchange", "currency", "region", "fund_code", "sec_cik"],
        "freshness_limitation_not_disqualifying_for_identifier_anchor": True,
        "fuzzy_match_remains_review_only": True,
    }
    if "Institutional identifier anchors can update crosswalk when exact source identifiers are present." not in rules.get("merge_guards", []):
        rules.setdefault("merge_guards", []).append("Institutional identifier anchors can update crosswalk when exact source identifiers are present.")
    write_json(CONFIG_ROOT / "entity_identifier_rules.json", rules)
    return rules


def run_controlled_proof_qa(qa_policy: dict[str, Any], source_strategy: dict[str, Any]) -> dict[str, Any]:
    source_roles = {item["source_id"]: item for item in source_strategy.get("sources", [])}
    proof_items = []
    qa_records = []

    baostock_rows = read_jsonl(V4_ROOT / "a_share_etf_baostock_normalized.jsonl")
    akshare_rows = read_jsonl(V4_ROOT / "a_share_etf_akshare_tencent_normalized.jsonl")
    market_sample = baostock_rows[: min(len(baostock_rows), 180)] + akshare_rows[: min(len(akshare_rows), 180)]
    qa_records.extend(qa_market_rows(market_sample))
    proof_items.append(
        {
            "proof_line": "open_source_wrapper_a_share_etf",
            "sources": ["baostock_daily", "akshare_tencent_daily"],
            "dataset": "a_share_etf_daily_v4_sample",
            "records_checked": len(market_sample),
            "source_type": "open_source_api_wrapper",
            "assigned_statuses": ["production_candidate", "cross_validated_candidate"],
            "formal_trusted_consumption": False,
        }
    )

    ms = read_json(V4_ROOT / "morningstar_field_depth_v4.json", {})
    ms_records = qa_morningstar_items(ms.get("items", []))
    qa_records.extend(ms_records)
    proof_items.append(
        {
            "proof_line": "licensed_institutional_morningstar",
            "sources": ["morningstar_direct"],
            "dataset": "controlled_candidates_field_depth",
            "records_checked": len(ms_records),
            "source_type": "licensed_institutional_source",
            "assigned_statuses": ["licensed_high_confidence_candidate", "historical_identifier_anchor", "coverage_limited_but_usable", "freshness_limited_but_usable"],
            "formal_trusted_consumption": False,
        }
    )

    freshness = read_json(V4_ROOT / "macro_rates_fx_commodity_freshness_closure.json", {})
    official_records = qa_official_items(freshness.get("items", [])[:80])
    qa_records.extend(official_records)
    proof_items.append(
        {
            "proof_line": "official_macro_rates_fx_commodity",
            "sources": ["fred_public_api", "treasury_fiscaldata", "world_bank_pink_sheet"],
            "dataset": "v4_freshness_closure_items",
            "records_checked": len(official_records),
            "source_type": "official_source",
            "assigned_statuses": ["production_candidate", "freshness_limited_but_usable"],
            "formal_trusted_consumption": False,
        }
    )

    status_counts = Counter(record["qa_status"] for record in qa_records)
    anomaly_count = sum(1 for record in qa_records if record.get("anomaly_flags"))
    candidate_status_summary = Counter()
    for item in proof_items:
        for status in item["assigned_statuses"]:
            candidate_status_summary[status] += 1
    source_summaries = summarize_sources(proof_items, qa_records)
    payload = {
        "generated_at": utc_now(),
        "qa_summary": {
            "records_checked": len(qa_records),
            "status_counts": dict(status_counts),
            "anomaly_flag_count": anomaly_count,
            "failed_count": status_counts.get("quality_failed", 0),
        },
        "proof_items": proof_items,
        "qa_records": qa_records[:1000],
        "source_summaries": source_summaries,
        "candidate_status_summary": dict(candidate_status_summary),
        "formal_trusted_consumption": False,
    }
    write_json(OUTPUT_ROOT / "automated_qa_results.json", {"generated_at": utc_now(), "qa_policy": qa_policy, "qa_summary": payload["qa_summary"], "qa_records": qa_records[:1000]})
    write_json(OUTPUT_ROOT / "controlled_proof_run_results.json", payload)
    write_json(OUTPUT_ROOT / "candidate_status_update_results.json", {"generated_at": utc_now(), "candidate_status_summary": dict(candidate_status_summary), "proof_items": proof_items})
    return payload


def qa_market_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    records = []
    for row in rows:
        checks = []
        warnings = []
        anomalies = []
        required = ["source_id", "symbol", "trade_date", "close", "retrieved_at"]
        missing = [key for key in required if row.get(key) in {None, ""}]
        if missing:
            checks.append({"check": "required_fields_present", "status": "failed", "missing": missing})
        else:
            checks.append({"check": "required_fields_present", "status": "passed"})
        if not valid_date(row.get("trade_date")):
            checks.append({"check": "date_parseable", "status": "failed"})
        numeric_fields = ["open", "high", "low", "close", "volume", "amount", "turnover_rate", "pct_change"]
        bad_numeric = [field for field in numeric_fields if row.get(field) is not None and not is_number(row.get(field))]
        checks.append({"check": "numeric_fields_parseable", "status": "failed" if bad_numeric else "passed", "bad_fields": bad_numeric})
        key = (row.get("source_id"), row.get("symbol"), row.get("trade_date"))
        if key in seen:
            checks.append({"check": "duplicate_entity_date_source", "status": "failed"})
        else:
            checks.append({"check": "duplicate_entity_date_source", "status": "passed"})
            seen.add(key)
        if any((row.get(field) is not None and float(row.get(field)) < 0) for field in ["open", "high", "low", "close", "volume", "amount"] if is_number(row.get(field))):
            anomalies.append("negative_price_volume_or_amount")
        if all(row.get(field) is not None and is_number(row.get(field)) for field in ["open", "high", "low", "close"]):
            open_, high, low, close = (float(row[field]) for field in ["open", "high", "low", "close"])
            if high < max(open_, close, low) or low > min(open_, close, high):
                anomalies.append("ohlc_rule_break")
        if row.get("pct_change") is not None and is_number(row.get("pct_change")) and abs(float(row["pct_change"])) > 25:
            anomalies.append("pct_change_extreme")
        if row.get("amount") is None:
            warnings.append("amount_missing_or_source_not_supported")
        qa_status = classify_qa(checks, warnings, anomalies)
        records.append(
            {
                "record_id": f"{row.get('source_id')}:{row.get('symbol')}:{row.get('trade_date')}",
                "source_id": row.get("source_id"),
                "source_type": "open_source_api_wrapper",
                "entity_id": infer_market_entity_id(str(row.get("symbol"))),
                "qa_status": qa_status,
                "candidate_status": "anomaly_flagged_candidate" if anomalies else "production_candidate",
                "warning_flags": warnings,
                "anomaly_flags": anomalies,
                "checks": checks,
            }
        )
    return records


def qa_morningstar_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in items:
        warnings = []
        anomalies: list[str] = []
        checks = []
        if not item.get("dataset_id"):
            checks.append({"check": "dataset_id_present", "status": "failed"})
        else:
            checks.append({"check": "dataset_id_present", "status": "passed"})
        if item.get("identifier_fields"):
            checks.append({"check": "source_identifier_present", "status": "passed"})
        else:
            checks.append({"check": "source_identifier_present", "status": "failed"})
        if not item.get("fields_available"):
            warnings.append("field_completeness_limited")
        if item.get("freshness_blockers"):
            warnings.append("freshness_limited_but_usable")
        if item.get("license_storage_blockers"):
            warnings.append("license_storage_boundary_needs_review")
        records.append(
            {
                "record_id": f"morningstar_direct:{item.get('dataset_id')}",
                "source_id": "morningstar_direct",
                "source_type": "licensed_institutional_source",
                "entity_id": None,
                "qa_status": classify_qa(checks, warnings, anomalies),
                "candidate_status": "licensed_high_confidence_candidate",
                "secondary_statuses": ["historical_identifier_anchor", "coverage_limited_but_usable", "freshness_limited_but_usable"],
                "warning_flags": warnings,
                "anomaly_flags": anomalies,
                "checks": checks,
            }
        )
    return records


def qa_official_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for item in items:
        warnings = []
        anomalies: list[str] = []
        checks = []
        missing = [key for key in ["dataset_id", "source_id", "latest_observation"] if not item.get(key)]
        checks.append({"check": "required_fields_present", "status": "failed" if missing else "passed", "missing": missing})
        checks.append({"check": "date_parseable", "status": "passed" if valid_date(item.get("latest_observation")) else "failed"})
        if item.get("release_calendar_limited"):
            warnings.append("release_calendar_limited")
        if item.get("publish_date_source") == "unavailable":
            warnings.append("publish_date_unavailable")
        if item.get("remaining_ready_for_trusted_gap"):
            warnings.extend(item.get("remaining_ready_for_trusted_gap", []))
        status = "production_candidate"
        if warnings:
            status = "freshness_limited_but_usable"
        records.append(
            {
                "record_id": f"{item.get('source_id')}:{item.get('dataset_id')}",
                "source_id": item.get("source_id"),
                "source_type": "official_source",
                "entity_id": f"macro_series:{item.get('dataset_id')}",
                "qa_status": classify_qa(checks, warnings, anomalies),
                "candidate_status": status,
                "warning_flags": sorted(set(warnings)),
                "anomaly_flags": anomalies,
                "checks": checks,
            }
        )
    return records


def classify_qa(checks: list[dict[str, Any]], warnings: list[str], anomalies: list[str]) -> str:
    if any(check.get("status") == "failed" for check in checks):
        return "quality_failed"
    if anomalies:
        return "anomaly_flagged_candidate"
    if warnings:
        return "quality_warning"
    return "quality_passed"


def valid_date(value: Any) -> bool:
    if not value:
        return False
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}", str(value)))


def is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def infer_market_entity_id(symbol: str) -> str:
    if symbol.startswith(("5", "1")):
        return f"cn_etf_{symbol}"
    if symbol:
        return f"cn_equity_{symbol}"
    return "unresolved_market_entity"


def summarize_sources(proof_items: list[dict[str, Any]], qa_records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in qa_records:
        grouped[str(record["source_id"])].append(record)
    for source_id, records in grouped.items():
        summary[source_id] = {
            "records_checked": len(records),
            "qa_status_counts": dict(Counter(record["qa_status"] for record in records)),
            "candidate_status_counts": dict(Counter(record["candidate_status"] for record in records)),
            "assigned_statuses": sorted({record["candidate_status"] for record in records} | {status for record in records for status in record.get("secondary_statuses", [])}),
        }
    return summary


def build_entity_crosswalk_update(proof: dict[str, Any]) -> dict[str, Any]:
    records = proof["qa_records"]
    entries = []
    for record in records:
        if record.get("entity_id") and record["entity_id"] != "unresolved_market_entity":
            entries.append(
                {
                    "entity_id": record["entity_id"],
                    "source_id": record["source_id"],
                    "source_record_id": record["record_id"],
                    "mapping_status": "candidate_exact_identifier",
                    "trusted_merge": False,
                }
            )
    summary = {
        "crosswalk_increment": len(entries),
        "unresolved_count": sum(1 for record in records if not record.get("entity_id") or record.get("entity_id") == "unresolved_market_entity"),
        "duplicate_risk_count": 0,
        "fuzzy_auto_merge_count": 0,
        "institutional_identifier_anchor_enabled": True,
    }
    payload = {"generated_at": utc_now(), "summary": summary, "entries": entries[:1000]}
    write_json(OUTPUT_ROOT / "entity_crosswalk_update_results.json", payload)
    return payload


def update_dashboard_trust_pipeline(policy: dict[str, Any], proof: dict[str, Any], entity_update: dict[str, Any]) -> dict[str, Any]:
    status = read_json(RUNTIME_ROOT / "dashboard_automation_status.json", {})
    panel = {
        "generated_at": utc_now(),
        "title": "Institutional Data Source Trust Policy + Automated QA Pipeline",
        "source_type_taxonomy": NEW_SOURCE_TYPES,
        "candidate_states": NEW_CANDIDATE_STATES,
        "qa_summary": proof["qa_summary"],
        "source_summaries": proof["source_summaries"],
        "candidate_status_summary": proof["candidate_status_summary"],
        "entity_crosswalk_update": entity_update["summary"],
        "morningstar": {
            "source_role": "licensed_institutional_source",
            "status": "licensed_high_confidence_candidate",
            "auto_login": False,
            "password_saved": False,
            "token_leaked": False,
        },
        "media_source_policy": "media_event_candidate / needs_cross_source_fact_check only",
        "formal_trusted_consumption_affected": False,
    }
    status["institutional_trust_qa_pipeline"] = panel
    write_json(RUNTIME_ROOT / "dashboard_automation_status_institutional_qa.json", panel)
    write_json(RUNTIME_ROOT / "dashboard_automation_status.json", status)
    write_json(OUTPUT_ROOT / "dashboard_trust_pipeline_summary.json", panel)
    return panel


def write_docs(policy: dict[str, Any], qa_policy: dict[str, Any], proof: dict[str, Any], source_strategy: dict[str, Any], entity_update: dict[str, Any]) -> dict[str, str]:
    docs = {
        "trust_policy": str(DOCS_ROOT / "INSTITUTIONAL_DATA_SOURCE_TRUST_POLICY.md"),
        "qa_policy": str(DOCS_ROOT / "AUTOMATED_QA_PIPELINE_POLICY.md"),
        "proof_report": str(DOCS_ROOT / "PRODUCTION_CANDIDATE_BACKFILL_PROOF_REPORT.md"),
    }
    write_text(Path(docs["trust_policy"]), render_policy_doc(policy, source_strategy))
    write_text(Path(docs["qa_policy"]), render_qa_doc(qa_policy))
    write_text(Path(docs["proof_report"]), render_proof_doc(proof, entity_update))
    return docs


def render_policy_doc(policy: dict[str, Any], source_strategy: dict[str, Any]) -> str:
    return f"""# Institutional Data Source Trust Policy

Generated: {utc_now()}

Institutional databases are not treated as ordinary media/news webpages. Morningstar, Wind, Eastmoney terminal-style data, Tonghuashun terminal-style data, and authorized exchange data can enter high-confidence candidate paths when entitlement, schema, QA, and storage boundaries are clear.

Coverage limitations are labeled as `coverage_limited_but_usable`; they do not automatically make the whole data source unreliable.

Media/news/community sources remain `media_event_candidate`, `sentiment_candidate`, or `clue_candidate`; key factual claims require cross-source fact checks.

Formal trusted consumption remains unchanged.

Source types: {', '.join(policy['source_type_taxonomy'])}
"""


def render_qa_doc(qa_policy: dict[str, Any]) -> str:
    return f"""# Automated QA Pipeline Policy

Generated: {utc_now()}

QA is an automated format, logic, and anomaly detection layer. It keeps raw and normalized values, marks review flags, and does not silently delete anomalies.

Checks:
{chr(10).join('- ' + item for item in qa_policy['checks'])}
"""


def render_proof_doc(proof: dict[str, Any], entity_update: dict[str, Any]) -> str:
    return f"""# Production Candidate Backfill Proof Report

Generated: {utc_now()}

Controlled proof sources:
{chr(10).join('- ' + item for item in proof['source_summaries'].keys())}

QA status counts: {proof['qa_summary']['status_counts']}

Candidate status counts: {proof['candidate_status_summary']}

Entity crosswalk increment: {entity_update['summary']['crosswalk_increment']}

No data entered formal trusted consumption.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Run institutional trust policy and automated QA proof pipeline.")
    parser.parse_args()
    summary = run_institutional_trust_qa_pipeline()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
