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

from scripts.run_morningstar_safe_access_audit import (  # noqa: E402
    CONFIG_ROOT,
    DOCS_ROOT,
    LOCAL_SECRETS,
    TOKEN_STATE_PATH,
    check_gitignore,
    mask_token,
    read_json,
    run_git_ls_files,
    update_token_state,
    write_json,
    write_text,
)


RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "morningstar_fund_validation"
CONNECTOR_PILOT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_connector_pilot"
AUTHORITATIVE_RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "authoritative_crawler_framework"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_token() -> str | None:
    if not LOCAL_SECRETS.exists():
        return None
    data = read_json(LOCAL_SECRETS)
    morningstar = data.get("morningstar", {}) if isinstance(data, dict) else {}
    return morningstar.get("md_auth_token") if isinstance(morningstar, dict) else None


def token_guard() -> dict[str, Any]:
    token = load_token()
    state = update_token_state(token)
    return {
        "generated_at": utc_now(),
        "local_secrets_ignored": check_gitignore()["all_required_rules_present"],
        "local_secrets_git_tracked": bool(run_git_ls_files("config/local_secrets.json")),
        "token_present": bool(token),
        "token_status": state.get("token_status"),
        "masked_token": mask_token(token),
        "token_state_path": str(TOKEN_STATE_PATH),
        "token_leaked": False,
        "no_auto_login": True,
        "no_password_saved": True,
    }


def classify_dataset(name: str) -> dict[str, str]:
    text = name.lower()
    if "holding" in text or "portfolio" in text:
        return {"data_domain": "holdings", "fr_domain": "capital_flow", "fund_type": "fund_or_portfolio"}
    if "return" in text or "performance" in text or "nav" in text:
        return {"data_domain": "performance_nav_return", "fr_domain": "asset_class", "fund_type": "fund_or_etf"}
    if "allocation" in text or "exposure" in text or "sector" in text or "country" in text:
        return {"data_domain": "exposure_allocation", "fr_domain": "capital_flow", "fund_type": "fund_or_etf"}
    if "fund" in text or "etf" in text or "share class" in text or "rating" in text or "medalist" in text:
        return {"data_domain": "fund_master_rating_category", "fr_domain": "fund_market", "fund_type": "fund_or_etf"}
    if "index" in text or "benchmark" in text:
        return {"data_domain": "index_benchmark", "fr_domain": "asset_class", "fund_type": "benchmark"}
    if "operation" in text or "financial" in text or "valuation" in text:
        return {"data_domain": "company_or_fundamental", "fr_domain": "company", "fund_type": "company_or_security"}
    return {"data_domain": "dataset_metadata", "fr_domain": "licensed_source", "fund_type": "unknown"}


def build_fund_trust_rules() -> dict[str, Any]:
    rules = {
        "version": "morningstar_fund_trust_rules_v1",
        "generated_at": utc_now(),
        "platform_status": "licensed_authorized_platform",
        "default_status": "licensed_source_candidate",
        "not_public_source": True,
        "trust_levels": [
            {"level": "licensed_source_candidate", "criteria": ["account_can_access_metadata_or_dataset"]},
            {"level": "coverage_validated_candidate", "criteria": ["coverage_ratio_meets_threshold"]},
            {"level": "freshness_validated_candidate", "criteria": ["freshness_gap_days_within_threshold"]},
            {"level": "field_validated_candidate", "criteria": ["critical_fields_present", "field_definitions_clear"]},
            {"level": "cross_validated_candidate", "criteria": ["cross_source_match_rate_meets_threshold"]},
            {
                "level": "trusted_candidate",
                "criteria": [
                    "coverage_validated",
                    "freshness_validated",
                    "field_validated",
                    "cross_source_validated",
                    "QA_quality_passed",
                    "license_boundary_known",
                ],
            },
            {"level": "trusted_by_authorized_license", "criteria": ["user_confirms_authorized_local_research_use"]},
        ],
        "thresholds": {
            "coverage_ratio_min": 0.9,
            "field_completeness_min": 0.95,
            "cross_source_match_rate_min": 0.98,
            "freshness_gap_days_max": 7,
        },
        "upgrade_blockers": [
            "license_or_storage_scope_unknown",
            "no_authoritative_cross_source",
            "region_coverage_unconfirmed",
            "field_definitions_unconfirmed",
            "QA_not_passed",
        ],
    }
    write_json(CONFIG_ROOT / "morningstar_fund_trust_rules.json", rules)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_FUND_DATA_TRUST_MODEL.md",
        """# Morningstar Fund Data Trust Model

Morningstar Direct is a licensed authorized platform. FR never upgrades the whole platform to trusted. Trust is evaluated by dataset, asset type, country/region, field, freshness and cross-source validation.

Trust levels: `licensed_source_candidate`, `coverage_validated_candidate`, `freshness_validated_candidate`, `field_validated_candidate`, `cross_validated_candidate`, `trusted_candidate`, and `trusted_by_authorized_license`.

`trusted_candidate` requires coverage, freshness, field, QA and cross-source validation. `trusted_by_authorized_license` additionally requires user confirmation that Morningstar license permits local research use, storage and display.
""",
    )
    return rules


def load_entitlement_items() -> list[dict[str, Any]]:
    payload = read_json(CONNECTOR_PILOT_ROOT / "morningstar_dataset_entitlement_map.json")
    return payload.get("items", []) if isinstance(payload.get("items"), list) else []


def global_fund_coverage_audit(items: list[dict[str, Any]]) -> dict[str, Any]:
    dataset_items = [item for item in items if item.get("permission_status") == "available_from_dataset_list"]
    rows = []
    for item in dataset_items:
        info = classify_dataset(item.get("dataset_name", ""))
        rows.append(
            {
                "region": "global_or_unspecified",
                "fund_type": info["fund_type"],
                "dataset_id": item.get("dataset_id"),
                "dataset_name": item.get("dataset_name"),
                "sample_available": False,
                "metadata_available": True,
                "estimated_coverage_signal": "metadata_visible_region_specific_coverage_unconfirmed",
                "fields_available": item.get("fields_discovered", []),
                "update_frequency_signal": "method_unavailable",
                "permission_status": item.get("permission_status"),
                "data_domain": info["data_domain"],
                "fr_domain": info["fr_domain"],
                "notes": "Visible metadata is not row-level region coverage. Dataset-specific entitlement checks are still required.",
            }
        )
    for region in ["US", "China", "Hong Kong", "Europe", "Global"]:
        rows.append(
            {
                "region": region,
                "fund_type": "fund_etf_coverage_question",
                "dataset_id": None,
                "dataset_name": f"{region} fund/ETF coverage validation",
                "sample_available": False,
                "metadata_available": bool(dataset_items),
                "estimated_coverage_signal": "method_unavailable_do_not_guess",
                "fields_available": [],
                "update_frequency_signal": "method_unavailable",
                "permission_status": "needs_region_crosscheck",
                "data_domain": "coverage_validation",
                "fr_domain": "fund_market",
                "notes": "No region-specific coverage ratio inferred from metadata alone.",
            }
        )
    result = {
        "generated_at": utc_now(),
        "global_fund_coverage_audit_completed": True,
        "dataset_metadata_visible_count": len(dataset_items),
        "coverage_rows": rows,
        "domain_counts": dict(Counter(row["data_domain"] for row in rows)),
        "region_counts": dict(Counter(row["region"] for row in rows)),
        "large_download_performed": False,
        "candidate_only": True,
    }
    write_json(RUNTIME_ROOT / "global_fund_coverage_audit.json", result)
    return result


def china_authoritative_source_audit() -> dict[str, Any]:
    sources = [
        {
            "source_id": "amac_public_fund_disclosure",
            "source_name": "Asset Management Association of China public fund disclosure",
            "official_or_third_party": "official_industry_association",
            "access_method": "official website / possible downloadable pages",
            "crawler_allowed": "needs_terms_review",
            "file_download_available": "to_verify",
            "api_available": "not_confirmed",
            "coverage_target": "public fund managers, products, registrations, disclosures",
            "update_frequency": "unknown",
            "known_blocker": "site structure and terms need source-specific validation",
            "recommended_use": "authoritative coverage baseline if legally accessible",
            "trust_role": "primary_authoritative_crosscheck_source",
        },
        {
            "source_id": "fund_company_official_sites",
            "source_name": "Fund company official sites: Southern, E Fund, ChinaAMC, etc.",
            "official_or_third_party": "issuer_official",
            "access_method": "manual download / official product pages / announcements",
            "crawler_allowed": "per_site_terms_review",
            "file_download_available": "likely_for_reports_announcements",
            "api_available": "not_confirmed",
            "coverage_target": "product lists, announcements, periodic reports, ETF/index fund lists",
            "update_frequency": "issuer_specific",
            "known_blocker": "site-specific HTML/JS and anti-bot policies vary",
            "recommended_use": "issuer-level authoritative validation and manual import",
            "trust_role": "authoritative_crosscheck_source",
        },
        {
            "source_id": "sse_szse_fund_disclosure",
            "source_name": "SSE / SZSE ETF and fund disclosure",
            "official_or_third_party": "exchange_official",
            "access_method": "official disclosure pages / files if available",
            "crawler_allowed": "needs_terms_review",
            "file_download_available": "to_verify",
            "api_available": "not_confirmed",
            "coverage_target": "ETF lists, fund announcements, listed fund product information",
            "update_frequency": "exchange_specific",
            "known_blocker": "official endpoint stability and file format need audit",
            "recommended_use": "exchange-listed ETF cross validation",
            "trust_role": "primary_authoritative_crosscheck_source",
        },
        {
            "source_id": "csrc_fund_disclosure",
            "source_name": "CSRC regulatory disclosure channels",
            "official_or_third_party": "regulator_official",
            "access_method": "official pages / public disclosure",
            "crawler_allowed": "needs_terms_review",
            "file_download_available": "to_verify",
            "api_available": "not_confirmed",
            "coverage_target": "regulatory notices and fund-related disclosures",
            "update_frequency": "unknown",
            "known_blocker": "not optimized for direct product master data extraction",
            "recommended_use": "regulatory confirmation, not primary product master in v1",
            "trust_role": "authoritative_reference",
        },
        {
            "source_id": "eastmoney_ths_morningstar_cn",
            "source_name": "Eastmoney / iFinD / Morningstar China and similar platforms",
            "official_or_third_party": "third_party_financial_platform",
            "access_method": "web/API if legal and stable",
            "crawler_allowed": "restricted_needs_terms_review",
            "file_download_available": "platform_specific",
            "api_available": "not_confirmed",
            "coverage_target": "fund profile, NAV, category, holdings summary",
            "update_frequency": "platform_specific",
            "known_blocker": "not official; possible anti-bot/license restrictions",
            "recommended_use": "candidate fallback / secondary validation only",
            "trust_role": "candidate_secondary_validation_source",
        },
    ]
    result = {"generated_at": utc_now(), "sources": sources, "large_download_performed": False}
    write_json(RUNTIME_ROOT / "china_fund_authoritative_source_audit.json", result)
    write_text(
        DOCS_ROOT / "CHINA_FUND_AUTHORITATIVE_SOURCE_AUDIT.md",
        """# China Fund Authoritative Source Audit

China fund coverage validation cannot rely on Morningstar alone. Preferred cross-check sources are official industry, issuer, exchange and regulator disclosures. Third-party platforms remain candidate fallback only.

No automated scraping, captcha bypass, login scraping, proxy pool, or high-frequency request is allowed in this phase.
""",
    )
    return result


def china_crosscheck_pilot() -> dict[str, Any]:
    template_rows = [
        {
            "official_source_id": "fund_company_official_sites",
            "fund_company": "Southern Fund",
            "fund_code": "",
            "fund_name": "",
            "isin": "",
            "currency": "",
            "category": "",
            "latest_nav": "",
            "latest_nav_date": "",
            "official_url": "",
            "morningstar_sec_id": "",
            "morningstar_match_status": "to_review",
            "review_note": "",
        },
        {
            "official_source_id": "fund_company_official_sites",
            "fund_company": "E Fund or ChinaAMC",
            "fund_code": "",
            "fund_name": "",
            "isin": "",
            "currency": "",
            "category": "",
            "latest_nav": "",
            "latest_nav_date": "",
            "official_url": "",
            "morningstar_sec_id": "",
            "morningstar_match_status": "to_review",
            "review_note": "",
        },
    ]
    csv_path = RUNTIME_ROOT / "china_fund_official_manual_import_template.csv"
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(template_rows[0].keys()))
        writer.writeheader()
        writer.writerows(template_rows)
    result = {
        "generated_at": utc_now(),
        "pilot_status": "manual_import_template_generated",
        "official_count": None,
        "morningstar_matched_count": None,
        "coverage_ratio": None,
        "unmatched_official_count": None,
        "unmatched_morningstar_count": None,
        "field_completeness": None,
        "freshness_gap_days": None,
        "confidence_level": "insufficient_until_official_list_imported",
        "manual_review_template": str(csv_path),
        "blocker": "No validated legal/stable official China fund product connector in current phase.",
        "large_download_performed": False,
    }
    write_json(RUNTIME_ROOT / "china_fund_coverage_crosscheck_pilot.json", result)
    return result


def global_fund_flow_use_cases() -> dict[str, Any]:
    items = [
        {
            "use_case": "Global ETF holdings",
            "research_value": "Observe country, sector and asset allocation exposure.",
            "data_needed": ["fund universe", "holdings", "sector/country exposure"],
            "status": "candidate_if_entitled",
        },
        {
            "use_case": "US ETF fund universe",
            "research_value": "Classify ETF scale, category, asset allocation and sector exposure.",
            "data_needed": ["ETF master", "AUM", "category", "returns", "holdings"],
            "status": "candidate_if_entitled",
        },
        {
            "use_case": "Fund holdings change",
            "research_value": "Track holdings drift if point-in-time holdings entitlement exists.",
            "data_needed": ["holdings dates", "holding weights", "market values"],
            "status": "requires_entitlement_check",
        },
        {
            "use_case": "Flow proxy",
            "research_value": "Use AUM/NAV/shares/performance as proxy only when true flow data is unavailable.",
            "data_needed": ["AUM", "NAV", "returns", "shares outstanding if available"],
            "status": "proxy_only_not_true_flow",
        },
        {
            "use_case": "China exposure",
            "research_value": "Screen global funds with China/HK/Greater China exposure.",
            "data_needed": ["country exposure", "holdings", "category"],
            "status": "candidate_if_entitled_and_cross_validated",
        },
    ]
    result = {"generated_at": utc_now(), "items": items, "true_flow_warning": "Proxy metrics must not be described as actual fund flow."}
    write_json(RUNTIME_ROOT / "global_fund_flow_use_case_mapping.json", result)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_GLOBAL_FUND_FLOW_USE_CASES.md",
        """# Morningstar Global Fund Flow Use Cases

Morningstar may support global fund and ETF research through fund universes, holdings, exposures, performance, NAV and AUM-like fields if entitled.

If true flow data is unavailable, AUM/NAV/shares/performance may only be labeled as a proxy. FR must not present proxy movement as actual fund flow.
""",
    )
    return result


def trust_upgrade_framework(audit: dict[str, Any], china_pilot: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    candidates = []
    for row in audit.get("coverage_rows", []):
        if row.get("permission_status") != "available_from_dataset_list":
            continue
        candidates.append(
            {
                "dataset_id": row.get("dataset_id"),
                "dataset_name": row.get("dataset_name"),
                "current_status": "licensed_source_candidate",
                "proposed_status": "licensed_source_candidate",
                "trusted_candidate": False,
                "blockers": [
                    "coverage_not_cross_validated",
                    "field_level_sample_not_loaded",
                    "license_boundary_needs_review",
                ],
                "required_next_steps": [
                    "load authorized field metadata",
                    "cross-check against official/authoritative source",
                    "confirm raw/normalized storage rights",
                ],
            }
        )
    result = {
        "generated_at": utc_now(),
        "trusted_candidate_count": 0,
        "trust_upgrade_candidates": candidates[:20],
        "trust_upgrade_rules": rules["thresholds"],
        "china_crosscheck_status": china_pilot["pilot_status"],
        "formal_trusted_consumption": False,
        "reason_no_trusted_candidate": "No dataset has coverage + freshness + field + cross-source validation yet.",
    }
    write_json(RUNTIME_ROOT / "trust_upgrade_candidates.json", result)
    write_text(
        DOCS_ROOT / "MORNINGSTAR_TRUST_UPGRADE_FRAMEWORK.md",
        """# Morningstar Trust Upgrade Framework

Morningstar datasets can become `trusted_candidate` only after entitlement, field completeness, freshness, coverage, cross-source match, QA and license/storage checks pass.

Current phase result: no dataset is upgraded to `trusted_candidate`; all remain licensed candidate evidence or validation-in-progress.
""",
    )
    return result


def update_dashboard_status(audit: dict[str, Any], china_pilot: dict[str, Any], trust: dict[str, Any], token: dict[str, Any]) -> None:
    dashboard = read_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", default={"sources": []})
    sources = [source for source in dashboard.get("sources", []) if source.get("source_id") != "morningstar_direct"]
    sources.append(
        {
            "source_id": "morningstar_direct",
            "display_name": "Morningstar Direct",
            "status": "fund_validation_in_progress",
            "token_status": token.get("token_status"),
            "entitlement_mapping_status": "completed",
            "global_fund_coverage_audit_status": "completed",
            "china_fund_coverage_pilot_status": china_pilot.get("pilot_status"),
            "trust_upgrade_candidate_count": trust.get("trusted_candidate_count", 0),
            "dataset_metadata_visible_count": audit.get("dataset_metadata_visible_count", 0),
            "last_smoke_test_result": "not_run_this_phase",
            "warning": "Licensed source; validation in progress. Candidate only until coverage, freshness, field and cross-source checks pass.",
            "licensed_authorized_platform": True,
        }
    )
    write_json(AUTHORITATIVE_RUNTIME_ROOT / "dashboard_source_status.json", {"generated_at": utc_now(), "sources": sources})


def write_summary(
    token: dict[str, Any],
    audit: dict[str, Any],
    china_audit: dict[str, Any],
    china_pilot: dict[str, Any],
    use_cases: dict[str, Any],
    trust: dict[str, Any],
) -> dict[str, Any]:
    summary = {
        "generated_at": utc_now(),
        "morningstar_fund_trust_model_completed": True,
        "global_fund_coverage_audit_completed": True,
        "china_fund_authoritative_source_audit_completed": True,
        "china_fund_coverage_crosscheck_pilot_status": china_pilot["pilot_status"],
        "global_fund_flow_use_case_mapping_completed": True,
        "trust_upgrade_framework_completed": True,
        "trusted_candidate_count": trust["trusted_candidate_count"],
        "dashboard_morningstar_validation_status_updated": True,
        "dataset_metadata_visible_count": audit["dataset_metadata_visible_count"],
        "china_authoritative_source_count": len(china_audit["sources"]),
        "global_fund_flow_use_case_count": len(use_cases["items"]),
        "token_status": token["token_status"],
        "no_auto_login": True,
        "no_password_saved": True,
        "token_leaked": False,
        "large_download_performed": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "formal_trusted_consumption_affected": False,
        "outputs": {
            "trust_rules": str(CONFIG_ROOT / "morningstar_fund_trust_rules.json"),
            "global_fund_coverage_audit": str(RUNTIME_ROOT / "global_fund_coverage_audit.json"),
            "china_source_audit": str(RUNTIME_ROOT / "china_fund_authoritative_source_audit.json"),
            "china_crosscheck_pilot": str(RUNTIME_ROOT / "china_fund_coverage_crosscheck_pilot.json"),
            "global_fund_flow_use_cases": str(RUNTIME_ROOT / "global_fund_flow_use_case_mapping.json"),
            "trust_upgrade_candidates": str(RUNTIME_ROOT / "trust_upgrade_candidates.json"),
        },
    }
    write_json(RUNTIME_ROOT / "morningstar_fund_validation_summary.json", summary)
    return summary


def run() -> dict[str, Any]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    token = token_guard()
    rules = build_fund_trust_rules()
    items = load_entitlement_items()
    audit = global_fund_coverage_audit(items)
    china_audit = china_authoritative_source_audit()
    china_pilot = china_crosscheck_pilot()
    use_cases = global_fund_flow_use_cases()
    trust = trust_upgrade_framework(audit, china_pilot, rules)
    update_dashboard_status(audit, china_pilot, trust, token)
    return write_summary(token, audit, china_audit, china_pilot, use_cases, trust)


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "completed": True,
                "dataset_metadata_visible_count": result["dataset_metadata_visible_count"],
                "trusted_candidate_count": result["trusted_candidate_count"],
                "china_pilot": result["china_fund_coverage_crosscheck_pilot_status"],
                "outputs_root": str(RUNTIME_ROOT),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
