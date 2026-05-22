"""Test Morningstar Full Backfill Batch 2A outputs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUNTIME = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
STATE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
NAS_STRUCTURED = Path("Z:/data_lake_master/structured/licensed/morningstar")
RUN_DATE = "20260522"


def read_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_entity_graph_schema() -> None:
    eg = read_json(STATE / "morningstar_entity_graph_schema.json")
    assert eg.get("schema_id")
    entities = eg.get("entities", {})
    for e in ["Organization", "Fund", "ShareClass", "Performance", "Portfolio", "Holding", "UnderlyingEntity"]:
        assert e in entities, f"Missing entity: {e}"
    rels = eg.get("relationships", [])
    assert len(rels) >= 6


def test_field_dictionary() -> None:
    fd = read_json(STATE / "morningstar_field_dictionary_direct_definitions.json")
    fields = {f["field_name"]: f for f in fd.get("fields", [])}
    for name in ["Fund Size", "Firm Name", "Net Assets - Share Class", "NAV", "Monthly Return", "Holdings", "Look-through Holdings", "TNA / ENF"]:
        assert name in fields, f"Missing field: {name}"
    assert fields["Fund Size"]["status"] == "blocked_unit_scale_unknown"
    assert fields["TNA / ENF"]["status"] == "blocked_unit_scale_unknown"
    assert fields["Monthly Return"]["status"] == "available"


def test_capital_pool_taxonomy() -> None:
    tax = read_json(STATE / "morningstar_capital_pool_taxonomy.json")
    pools = {p["pool_id"]: p for p in tax.get("pools", [])}
    assert "high_frequency_public_traded" in pools
    assert "medium_frequency_allocation" in pools
    assert "low_frequency_stable" in pools
    assert "not_covered" in pools
    hf = pools["high_frequency_public_traded"]
    assert hf["capital_flow_proxy_relevance"] == "high"
    assert any(c["name"] == "ETF" for c in hf["categories"])


def test_update_frequency_inventory() -> None:
    inv = read_json(STATE / "morningstar_update_frequency_inventory.json")
    methods = {m["method"]: m for m in inv.get("methods", [])}
    assert "md.direct.get_returns" in methods
    assert methods["md.direct.get_returns"]["frequency"] == "monthly"
    flags = inv.get("availability_flags", {})
    assert flags.get("daily_data_available_flag") is True
    assert flags.get("nav_available_flag") is False
    assert flags.get("fund_size_available_flag") is False


def test_dataset_inventory_batch2a() -> None:
    inv = read_json(STATE / "morningstar_method_dataset_inventory_batch2a.json")
    datasets = {d["dataset_id"]: d for d in inv.get("datasets", [])}
    assert "method:md.direct.get_asset_flow" in datasets
    assert datasets["method:md.direct.get_asset_flow"].get("blocked") is True


def test_relationship_discovery_report() -> None:
    rep = read_json(STATE / "morningstar_relationship_discovery_report.json")
    findings = rep.get("findings", [])
    assert len(findings) >= 5
    anomalies = rep.get("anomalies", [])
    assert len(anomalies) >= 1


def test_etf_universe_candidate() -> None:
    etf = read_json(RUNTIME / "batch2a" / "morningstar_etf_universe_candidate.json")
    assert etf.get("total_candidates", 0) > 0
    assert all(c.get("security_type") in ("FE", "ETF") for c in etf.get("candidates", []))


def test_daily_capable_universe() -> None:
    du = read_json(RUNTIME / "batch2a" / "morningstar_daily_capable_universe.json")
    assert du.get("total_candidates", 0) > 0


def test_id_crosswalk_batch2a() -> None:
    cw = read_json(RUNTIME / "batch2a" / "morningstar_id_crosswalk_batch2a.json")
    assert len(cw.get("mappings", [])) > 0
    for m in cw["mappings"]:
        assert m.get("secId")


def test_qa_summary_batch2a() -> None:
    qa = read_json(RUNTIME / "qa" / f"batch2a_qa_summary_{RUN_DATE}.json")
    assert qa.get("overall_status") in ("passed", "passed_with_warnings")
    assert qa.get("us_equity_standalone_excluded") is True
    assert qa.get("blocked_fields_present") is False


def test_failure_log_batch2a() -> None:
    fl = read_json(STATE / "batch2a_failure_log.json")
    assert "entries" in fl


def test_run_state_updated() -> None:
    rs = read_json(STATE / "run_state.json")
    assert rs.get("batch2a_completed") is True
    assert rs.get("batch2a_run_id", "").startswith("batch2a_")
    assert rs.get("next_step") in ("batch2b_dry_run_plan_or_incremental", "token_refresh_required_before_batch2c", "batch2c_plan_or_incremental", "batch3_or_incremental_or_report_generation", "batch3_run2_or_incremental_or_time_series_size_collection", "batch3_run3_or_incremental_or_time_series_size_collection", "batch3_run4_or_incremental_or_time_series_deepening")


def test_nas_structured_batch2a() -> None:
    nas = NAS_STRUCTURED / RUN_DATE / "batch2a"
    assert nas.exists()
    required = [
        "morningstar_entity_graph_schema.json",
        "morningstar_field_dictionary_direct_definitions.json",
        "morningstar_capital_pool_taxonomy.json",
        "morningstar_update_frequency_inventory.json",
    ]
    for name in required:
        assert (nas / name).exists(), f"Missing NAS structured file: {name}"


if __name__ == "__main__":
    tests = [
        test_entity_graph_schema,
        test_field_dictionary,
        test_capital_pool_taxonomy,
        test_update_frequency_inventory,
        test_dataset_inventory_batch2a,
        test_relationship_discovery_report,
        test_etf_universe_candidate,
        test_daily_capable_universe,
        test_id_crosswalk_batch2a,
        test_qa_summary_batch2a,
        test_failure_log_batch2a,
        test_run_state_updated,
        test_nas_structured_batch2a,
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
    sys.exit(0 if failed == 0 else 1)
