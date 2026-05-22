"""
Test suite for Morningstar Full Backfill Batch 2B Rerun
Validates real API backfill artifacts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_STATE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
LOCAL_RUNTIME = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
RUN_DATE = "20260522"


def read_json(path: Path) -> Any:
    assert path.exists(), f"Missing file: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_field_inventory_exists():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    assert inv.get("inventory_id")
    assert inv.get("total_fields", 0) >= 40
    fields = inv.get("fields", [])
    assert len(fields) >= 40


def test_known_direct_fields_present():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    field_ids = {f["raw_field_id"] for f in inv.get("fields", [])}
    required = {"FundSize", "NetAssetsShareClass", "VehicleAssets", "NAV", "FirmName", "Universe", "TNA"}
    missing = required - field_ids
    assert not missing, f"Missing known Direct fields: {missing}"


def test_fund_size_definition():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    fund_size = next((f for f in inv["fields"] if f["raw_field_id"] == "FundSize"), None)
    assert fund_size is not None
    assert "standalone portfolio" in fund_size.get("definition", "").lower()
    assert fund_size.get("semantic_group") == "fund_level_size"
    assert fund_size.get("size_measure_type") == "fund_size"


def test_vehicle_assets_definition():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    va = next((f for f in inv["fields"] if f["raw_field_id"] == "VehicleAssets"), None)
    assert va is not None
    assert "trust" in va.get("definition", "").lower()
    assert va.get("semantic_group") == "vehicle_or_trust_level_size"


def test_universe_is_exposure_scope_not_etf_flag():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    u = next((f for f in inv["fields"] if f["raw_field_id"] == "Universe"), None)
    assert u is not None
    assert u.get("semantic_group") == "exposure_scope"
    assert "NOT be used as ETF product type flag" in u.get("reviewer_notes", "")


def test_tna_blocked():
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    tna = next((f for f in inv["fields"] if f["raw_field_id"] == "TNA"), None)
    assert tna is not None
    assert tna.get("validation_status") == "blocked_unit_scale_unknown"
    assert "blocked" in tna.get("reviewer_notes", "").lower()


def test_semantic_field_map_exists():
    mp = read_json(LOCAL_STATE / "morningstar_semantic_field_map_batch2b.json")
    assert mp.get("map_id")
    groups = mp.get("semantic_groups", {})
    assert len(groups) >= 10
    required_groups = {
        "fund_level_size",
        "shareclass_level_size",
        "vehicle_or_trust_level_size",
        "nav_or_share_price",
        "returns",
        "holdings_weight",
        "organization_identifier",
        "exposure_scope",
    }
    missing = required_groups - set(groups.keys())
    assert not missing, f"Missing semantic groups: {missing}"


def test_size_field_candidates():
    cand = read_json(LOCAL_STATE / "morningstar_size_field_candidates_batch2b.json")
    items = cand.get("candidates", [])
    assert len(items) >= 5
    types = {i["size_measure_type"] for i in items}
    assert "fund_size" in types
    assert "shareclass_net_assets" in types
    assert "vehicle_or_trust_assets" in types
    assert "unknown_or_blocked" in types
    ids = {i["raw_field_id"] for i in items}
    assert "stepSize" not in ids
    assert "windowSize" not in ids


def test_fund_flow_universe_exists():
    uni = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json")
    assert uni.get("universe_id")
    candidates = uni.get("candidates", [])
    assert len(candidates) == 88


def test_fund_flow_universe_has_size_and_holdings_flags():
    uni = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json")
    for c in uni.get("candidates", []):
        assert "size_field_available_flag" in c
        assert "holdings_available_flag" in c
        assert "nav_available_flag" in c
        assert "returns_available_flag" in c


def test_holdings_availability_report():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_holdings_availability_report.json")
    assert rep.get("total_holdings_records", 0) > 0
    assert rep.get("unique_investments_with_holdings", 0) > 0
    fields = rep.get("fields_present", [])
    assert "weight" in fields
    assert "marketValue" in fields


def test_nav_returns_availability_report():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_nav_returns_availability_report.json")
    assert rep.get("nav_available_count", 0) > 0
    assert rep.get("returns_available_count", 0) > 0
    assert rep.get("total_returns_records", 0) > 0


def test_size_field_availability_report():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_size_field_availability_report.json")
    avail = rep.get("availability", {})
    assert avail.get("fund_size_of009", 0) > 0
    assert avail.get("net_assets_shareclass_os013", 0) > 0
    assert avail.get("nav_daily_os060", 0) > 0


def test_field_definition_validation_report():
    rep = read_json(LOCAL_STATE / "morningstar_field_definition_validation_report_batch2b.json")
    summary = rep.get("summary", {})
    assert summary.get("semantic_definition_match", 0) >= 5
    assert summary.get("blocked_unit_scale_unknown", 0) >= 1


def test_numeric_sanity_check():
    rep = read_json(LOCAL_STATE / "morningstar_numeric_sanity_check_batch2b.json")
    assert rep.get("total_checked", 0) > 0
    # Anomalies are warnings, not failures
    assert rep.get("anomalies_found", -1) >= 0


def test_entity_crosswalk_update():
    cw = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_entity_crosswalk_update.json")
    assert cw.get("new_mappings_count", -1) == 0


def test_dedupe_report():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_dedupe_report.json")
    assert rep.get("conflict", -1) == 0
    assert rep.get("unresolved", -1) == 0


def test_field_coverage():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_field_coverage.json")
    cov = rep.get("coverage_by_field", {})
    assert cov.get("Fund Size", 0) > 0
    assert cov.get("Net Assets - Share Class", 0) > 0
    assert cov.get("NAV (Daily)", 0) > 0


def test_schema_coverage():
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_schema_coverage.json")
    sc = rep.get("schema_coverage", {})
    assert sc.get("Organization / Firm") is True
    assert sc.get("Fund") is True
    assert sc.get("ShareClass") is True
    assert sc.get("Performance / NAV") is True
    assert sc.get("Portfolio / Holdings") is True


def test_qa_summary():
    qa = read_json(LOCAL_RUNTIME / "qa" / f"batch2b_qa_summary_{RUN_DATE}.json")
    assert qa.get("overall_status") == "passed_with_warnings"
    checks = qa.get("checks", {})
    assert checks.get("token_valid") is True
    assert checks.get("size_fields_present") is True
    assert checks.get("nav_present") is True
    assert checks.get("us_equity_standalone_excluded") is True
    assert checks.get("tna_enf_blocked") is True
    assert checks.get("formal_trusted_consumption_enabled") is False
    assert checks.get("parse_lab_affected") is False


def test_failure_log():
    fl = read_json(LOCAL_STATE / "batch2b_failure_log.json")
    assert "failures" in fl


def test_retry_queue():
    rq = read_json(LOCAL_STATE / "batch2b_retry_queue.json")
    assert "items" in rq


def test_manifest():
    mf = read_json(LOCAL_RUNTIME / "manifest" / f"batch2b_manifest_{RUN_DATE}_rerun.json")
    assert mf.get("run_id", "").startswith("batch2b_rerun_")
    assert mf.get("api_calls", 0) > 0
    artifacts = mf.get("artifacts", [])
    assert len(artifacts) >= 10


def test_checkpoint():
    cp = read_json(LOCAL_STATE / f"checkpoint_after_batch2b_rerun_{RUN_DATE}.json")
    assert cp.get("status") == "completed"
    assert cp.get("api_calls", 0) > 0


def test_run_state_updated():
    state = read_json(LOCAL_STATE / "run_state.json")
    assert state.get("batch2b_completed") is True
    assert state.get("batch2b_api_calls", 0) > 0
    summary = state.get("batch2b_artifact_summary", {})
    assert summary.get("field_inventory_count", 0) >= 40
    assert summary.get("semantic_groups_count", 0) >= 10
    assert summary.get("size_candidates_count", 0) >= 5
    assert summary.get("fund_flow_universe_count") == 88
    blockers = state.get("blockers", [])
    assert not any(b.get("type") == "token_expired" for b in blockers)
    assert state.get("next_step") == "batch2c_plan_or_incremental"


if __name__ == "__main__":
    tests = [
        test_field_inventory_exists,
        test_known_direct_fields_present,
        test_fund_size_definition,
        test_vehicle_assets_definition,
        test_universe_is_exposure_scope_not_etf_flag,
        test_tna_blocked,
        test_semantic_field_map_exists,
        test_size_field_candidates,
        test_fund_flow_universe_exists,
        test_fund_flow_universe_has_size_and_holdings_flags,
        test_holdings_availability_report,
        test_nav_returns_availability_report,
        test_size_field_availability_report,
        test_field_definition_validation_report,
        test_numeric_sanity_check,
        test_entity_crosswalk_update,
        test_dedupe_report,
        test_field_coverage,
        test_schema_coverage,
        test_qa_summary,
        test_failure_log,
        test_retry_queue,
        test_manifest,
        test_checkpoint,
        test_run_state_updated,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {e}")
            failed += 1
    print(f"\nResults: {passed} passed, {failed} failed, {len(tests)} total")
