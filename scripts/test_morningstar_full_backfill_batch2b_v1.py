"""
Test suite for Morningstar Full Backfill Batch 2B
Validates all offline-generated artifacts.
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
RUN_DATE = "20260522"  # test against today's run


def read_json(path: Path) -> Any:
    assert path.exists(), f"Missing file: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_field_inventory_exists() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    assert inv.get("inventory_id")
    assert inv.get("total_fields", 0) > 50
    fields = inv.get("fields", [])
    assert len(fields) >= 50


def test_known_direct_fields_present() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    field_ids = {f["raw_field_id"] for f in inv.get("fields", [])}
    required = {"FundSize", "NetAssetsShareClass", "VehicleAssets", "NAV", "FirmName", "Universe", "TNA"}
    missing = required - field_ids
    assert not missing, f"Missing known Direct fields: {missing}"


def test_fund_size_definition() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    fund_size = next((f for f in inv["fields"] if f["raw_field_id"] == "FundSize"), None)
    assert fund_size is not None
    assert "standalone portfolio" in fund_size.get("definition", "").lower()
    assert fund_size.get("entity_level") == "Fund"
    assert fund_size.get("semantic_group") == "fund_level_size"
    assert fund_size.get("size_measure_type") == "fund_size"


def test_vehicle_assets_definition() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    va = next((f for f in inv["fields"] if f["raw_field_id"] == "VehicleAssets"), None)
    assert va is not None
    assert "trust" in va.get("definition", "").lower()
    assert va.get("entity_level") == "Fund/Vehicle/Trust"
    assert va.get("semantic_group") == "vehicle_or_trust_level_size"


def test_universe_is_exposure_scope_not_etf_flag() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    u = next((f for f in inv["fields"] if f["raw_field_id"] == "Universe"), None)
    assert u is not None
    assert u.get("semantic_group") == "exposure_scope"
    assert "NOT be used as ETF product type flag" in u.get("reviewer_notes", "")


def test_tna_blocked() -> None:
    inv = read_json(LOCAL_STATE / "morningstar_full_field_inventory_batch2b.json")
    tna = next((f for f in inv["fields"] if f["raw_field_id"] == "TNA"), None)
    assert tna is not None
    assert tna.get("validation_status") == "blocked_unit_scale_unknown"
    assert "BLOCKED" in tna.get("reviewer_notes", "")


def test_semantic_field_map_exists() -> None:
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
        "holding_identifier",
        "organization_identifier",
        "exposure_scope",
    }
    missing = required_groups - set(groups.keys())
    assert not missing, f"Missing semantic groups: {missing}"


def test_size_field_candidates() -> None:
    cand = read_json(LOCAL_STATE / "morningstar_size_field_candidates_batch2b.json")
    items = cand.get("candidates", [])
    assert len(items) >= 8
    types = {i["size_measure_type"] for i in items}
    assert "fund_size" in types
    assert "shareclass_net_assets" in types
    assert "vehicle_or_trust_assets" in types
    assert "unknown_or_blocked" in types
    # stepSize / windowSize must NOT appear
    ids = {i["field_id"] for i in items}
    assert "stepSize" not in ids
    assert "windowSize" not in ids


def test_fund_flow_universe_exists() -> None:
    uni = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json")
    assert uni.get("universe_id")
    candidates = uni.get("candidates", [])
    assert len(candidates) == 88


def test_fund_flow_universe_has_size_and_holdings_flags() -> None:
    uni = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_daily_weekly_fund_flow_universe.json")
    for c in uni.get("candidates", []):
        assert "daily_or_weekly_data_available" in c
        assert "size_field_available" in c
        assert "holdings_available" in c
        assert "identifiers_complete_enough" in c
        assert "capital_pool_classification" in c


def test_holdings_availability_report() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_holdings_availability_report.json")
    avail = rep.get("availability", {})
    assert avail.get("holdings_data_present") is True
    assert avail.get("weight_present") is True
    assert avail.get("market_value_present") is True
    assert avail.get("isin_present") is True


def test_nav_returns_availability_report() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_nav_returns_availability_report.json")
    avail = rep.get("availability", {})
    assert avail.get("monthly_returns_present") is True
    assert avail.get("nav_explicit_field_present") is False


def test_size_field_availability_report() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_size_field_availability_report.json")
    by_type = rep.get("by_type", {})
    assert "fund_size" in by_type
    assert "shareclass_net_assets" in by_type
    assert "vehicle_or_trust_assets" in by_type


def test_field_definition_validation_report() -> None:
    rep = read_json(LOCAL_STATE / "morningstar_field_definition_validation_report_batch2b.json")
    assert rep.get("semantic_definition_match", 0) >= 5
    assert rep.get("field_name_match_only", 0) >= 0
    assert rep.get("blocked_unit_scale_unknown", 0) >= 1


def test_numeric_sanity_check_pending() -> None:
    rep = read_json(LOCAL_STATE / "morningstar_numeric_sanity_check_batch2b.json")
    assert rep.get("status") == "pending_api_validation"


def test_entity_crosswalk_update() -> None:
    cw = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_entity_crosswalk_update.json")
    assert cw.get("new_mappings", -1) == 0  # all already in Batch 2A crosswalk
    assert cw.get("existing_mappings", 0) > 0


def test_dedupe_report() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_dedupe_report.json")
    assert rep.get("conflicts", -1) == 0
    assert rep.get("unresolved", -1) == 0


def test_field_coverage() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_field_coverage.json")
    req = rep.get("required_groups_present", {})
    assert req.get("fund_level_size") is True
    assert req.get("shareclass_level_size") is True
    assert req.get("vehicle_or_trust_level_size") is True
    assert req.get("nav_or_share_price") is True
    assert req.get("returns") is True


def test_schema_coverage() -> None:
    rep = read_json(LOCAL_RUNTIME / "batch2b" / "batch2b_schema_coverage.json")
    levels = rep.get("entity_level_coverage", {})
    assert "Fund" in levels or "Fund/ShareClass" in levels
    assert "ShareClass" in levels or "Fund/ShareClass" in levels
    assert "Portfolio" in levels or "Portfolio/Holding" in levels


def test_qa_summary() -> None:
    qa = read_json(LOCAL_RUNTIME / "qa" / f"batch2b_qa_summary_{RUN_DATE}.json")
    assert qa.get("overall_status") == "passed_with_warnings"
    assert qa.get("us_equity_standalone_excluded") is True
    assert qa.get("blocked_fields_present") is False
    assert qa.get("token_status") == "expired"
    assert qa.get("user_action_required")


def test_failure_log() -> None:
    fl = read_json(LOCAL_STATE / "batch2b_failure_log.json")
    entries = fl.get("entries", [])
    assert len(entries) >= 1
    assert any("TokenExpired" in e.get("error_type", "") for e in entries)


def test_retry_queue() -> None:
    rq = read_json(LOCAL_STATE / "batch2b_retry_queue.json")
    entries = rq.get("entries", [])
    assert len(entries) >= 1
    assert any("token" in e.get("reason", "").lower() for e in entries)


def test_manifest() -> None:
    mf = read_json(LOCAL_RUNTIME / "manifest" / f"batch2b_manifest_{RUN_DATE}.json")
    assert mf.get("run_id", "").startswith("batch2b_")
    assert mf.get("api_calls") == 0
    artifacts = mf.get("artifacts", {})
    required = {
        "morningstar_full_field_inventory_batch2b.json",
        "morningstar_semantic_field_map_batch2b.json",
        "morningstar_size_field_candidates_batch2b.json",
        "batch2b_daily_weekly_fund_flow_universe.json",
        "batch2b_qa_summary.json",
        "batch2b_failure_log.json",
        "batch2b_retry_queue.json",
        "batch2b_checkpoint.json",
    }
    missing = required - set(artifacts.keys())
    assert not missing, f"Missing manifest artifacts: {missing}"


def test_checkpoint() -> None:
    cp = read_json(LOCAL_STATE / f"checkpoint_after_batch2b_{RUN_DATE}.json")
    assert cp.get("status") == "completed_offline_pending_api_validation"
    assert cp.get("token_expired") is True


def test_run_state_updated() -> None:
    state = read_json(LOCAL_STATE / "run_state.json")
    assert state.get("batch2b_completed") is True
    assert state.get("batch2b_api_calls") == 0
    summary = state.get("batch2b_artifact_summary", {})
    assert summary.get("field_inventory_count", 0) >= 50
    assert summary.get("semantic_groups_count", 0) >= 10
    assert summary.get("size_candidates_count", 0) >= 8
    assert summary.get("fund_flow_universe_count") == 88
    blockers = state.get("blockers", [])
    assert any(b.get("type") == "token_expired" for b in blockers)
    assert state.get("next_step") == "token_refresh_required_before_batch2c"


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
        test_numeric_sanity_check_pending,
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
