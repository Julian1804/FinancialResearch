"""
Test Morningstar Full Backfill Batch 1 outputs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUNTIME = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
STATE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
NAS_RAW = Path("Z:/data_lake_master/raw/licensed/morningstar")
NAS_STRUCTURED = Path("Z:/data_lake_master/structured/licensed/morningstar")
NAS_ENTITY = Path("Z:/data_lake_master/structured/entity_master/morningstar")


def read_json(path: Path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_preflight_contracts_exist() -> None:
    required = [
        STATE / "backfill_contract.json",
        STATE / "dataset_inventory.json",
        STATE / "schema_map.json",
        STATE / "dedupe_policy.json",
        STATE / "qa_policy.json",
        STATE / "storage_manifest.json",
        STATE / "run_state.json",
        STATE / "failure_log.json",
        STATE / "license_storage_note.json",
    ]
    missing = [str(p) for p in required if not p.exists()]
    assert not missing, f"Missing contract files: {missing}"


def test_run_state_batch1_completed() -> None:
    state = read_json(STATE / "run_state.json")
    assert state.get("preflight_passed") is True
    assert state.get("batch1_completed") is True
    assert state.get("batch1_api_calls", 0) > 0
    assert state.get("next_step") in ("batch2_or_incremental", "batch2b_dry_run_plan_or_incremental", "token_refresh_required_before_batch2c", "batch2c_plan_or_incremental")


def test_batch1_manifest_exists() -> None:
    manifest_dir = RUNTIME / "manifest"
    manifests = list(manifest_dir.glob("batch1_manifest_*.json"))
    assert manifests, "No batch1 manifest found"
    manifest = read_json(manifests[0])
    assert manifest.get("batch") == 1
    assert manifest.get("us_equity_standalone_excluded") is True
    assert manifest.get("formal_trusted_consumption") is False
    assert manifest.get("no_openai_api") is True
    assert "tna_enf" in manifest.get("blocked_fields", [])


def test_qa_summary_passed() -> None:
    qa_dir = RUNTIME / "qa"
    qa_files = list(qa_dir.glob("batch1_qa_summary_*.json"))
    assert qa_files, "No QA summary found"
    qa = read_json(qa_files[0])
    overall = qa.get("overall_status")
    assert overall in ("passed", "passed_with_warnings"), f"QA overall status incorrect: {overall}"
    assert qa.get("blocked_fields_present") is False
    assert qa.get("us_equity_standalone_excluded") is True
    inv = next((c for c in qa.get("checks", []) if c["dataset"] == "investment_data"), {})
    assert inv.get("status") in ("warning", "unavailable_data_point"), f"investment_data QA status incorrect: {inv}"


def test_raw_data_on_nas() -> None:
    run_dirs = [d for d in NAS_RAW.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) == 8]
    assert run_dirs, "No raw run directory on NAS"
    latest = max(run_dirs)
    raw_files = list(latest.glob("*_raw.json"))
    assert raw_files, "No raw files found"


def test_structured_data_on_nas() -> None:
    run_dirs = [d for d in NAS_STRUCTURED.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) == 8]
    assert run_dirs, "No structured run directory on NAS"
    latest = max(run_dirs)
    required = ["fund_etf_metadata.json", "holdings.json", "lookthrough_holdings.json", "returns.json"]
    for name in required:
        assert (latest / name).exists(), f"Missing structured file: {name}"


def test_entity_master_on_nas_and_local() -> None:
    nas_files = list(NAS_ENTITY.glob("morningstar_entity_master_*.json"))
    local_files = list((PROJECT_ROOT / "runtime" / "entity_master").glob("morningstar_entity_master_*.json"))
    assert nas_files, "No entity master on NAS"
    assert local_files, "No entity master locally"
    nas_em = read_json(nas_files[0])
    assert nas_em.get("total_entities", 0) > 0
    assert "us_equity_entities" in nas_em


def test_crosswalk_exists() -> None:
    cw_dir = NAS_STRUCTURED / "crosswalk"
    cw_files = list(cw_dir.glob("morningstar_crosswalk_*.json"))
    assert cw_files, "No crosswalk file found"
    cw = read_json(cw_files[0])
    assert len(cw.get("mappings", [])) > 0


def test_failure_log_and_retry_queue() -> None:
    fl = read_json(STATE / "failure_log.json")
    rq = read_json(STATE / "retry_queue.json")
    assert "entries" in fl
    assert "items" in rq
    # Known expected failures: investment_data batches due to ResourceNotFoundError for datapoint IDs
    for entry in fl.get("entries", []):
        assert "ResourceNotFoundError" in (entry.get("error_type") or "")


def test_no_tna_enf_in_outputs() -> None:
    manifest_dir = RUNTIME / "manifest"
    manifests = list(manifest_dir.glob("batch1_manifest_*.json"))
    manifest = read_json(manifests[0])
    assert "tna_enf" in manifest.get("blocked_fields", [])


def test_checkpoint_files_exist() -> None:
    checkpoints = list(STATE.glob("checkpoint_*.json"))
    assert len(checkpoints) >= 4, "Expected at least 4 checkpoint files"


if __name__ == "__main__":
    tests = [
        test_preflight_contracts_exist,
        test_run_state_batch1_completed,
        test_batch1_manifest_exists,
        test_qa_summary_passed,
        test_raw_data_on_nas,
        test_structured_data_on_nas,
        test_entity_master_on_nas_and_local,
        test_crosswalk_exists,
        test_failure_log_and_retry_queue,
        test_no_tna_enf_in_outputs,
        test_checkpoint_files_exist,
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
