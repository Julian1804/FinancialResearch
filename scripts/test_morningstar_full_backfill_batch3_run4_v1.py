"""Test suite for Morningstar Batch 3 Run 4"""
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260523'
STRUCTURED_DIR = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / RUN_DATE / 'batch3_run4'

def read_json(path):
    assert path.exists(), f"Missing file: {path}"
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

passed = 0; failed = 0
def check(name, condition):
    global passed, failed
    if condition: print(f"PASS: {name}"); passed += 1
    else: print(f"FAIL: {name}"); failed += 1

# 1. Universe
univ = read_json(LOCAL_RUNTIME / 'batch3_run4' / 'batch3_run4_expanded_universe.json')
check("universe_exists", "batch3_run4" in univ.get("universe_id", ""))
check("universe_10k", univ.get("total_candidates", 0) >= 10000)
check("universe_exact", univ.get("total_candidates", 0) == 12951)

# 2. Investment data panel
inv = read_json(STRUCTURED_DIR / 'batch3_run4_investment_data_panel.json')
check("inv_panel_exists", "batch3_run4" in inv.get("panel_id", ""))
check("inv_panel_10k", inv.get("total_records", 0) >= 10000)

# 3. Returns panel
ret = read_json(STRUCTURED_DIR / 'batch3_run4_returns_panel.json')
check("returns_panel_exists", "batch3_run4" in ret.get("panel_id", ""))
check("returns_records", ret.get("total_records", 0) > 0)

# 4. Holdings panel
hold = read_json(STRUCTURED_DIR / 'batch3_run4_holdings_panel.json')
check("holdings_panel_exists", "batch3_run4" in hold.get("panel_id", ""))
check("holdings_records", hold.get("total_records", 0) > 0)

# 5. Underlying entity panel
ue = read_json(STRUCTURED_DIR / 'batch3_run4_underlying_entity_panel.json')
check("underlying_panel_exists", "batch3_run4" in ue.get("panel_id", ""))
check("underlying_entities_count", ue.get("total_entities", 0) > 0)
check("non_china_shell_only", all(e.get("timeseries_policy") == "entity_shell_only" for e in ue.get("records", []) if not e.get("is_china_equity")))

# 6. Flow Proxy
fp = read_json(STRUCTURED_DIR / 'batch3_run4_flow_proxy_panel.json')
check("flow_proxy_exists", "batch3_run4" in fp.get("panel_id", ""))
check("flow_proxy_10k", fp.get("total_records", 0) >= 10000)
check("flow_proxy_is_proxy", all(r.get("is_proxy_not_actual_flow") for r in fp.get("records", [])))

# 7. TNA/ENF sidecar
tna = read_json(STRUCTURED_DIR / 'batch3_run4_tna_enf_sidecar_summary.json')
check("tna_enf_exists", "batch3_run4" in tna.get("summary_id", ""))
check("tna_enf_blocked", tna.get("blocked_unit_scale_unknown") is True)

# 8. Crosswalk / Dedupe
dedupe = read_json(STRUCTURED_DIR / 'batch3_run4_dedupe_report.json')
check("dedupe_exists", "batch3_run4" in dedupe.get("report_id", ""))
check("dedupe_conflict", dedupe.get("conflict", -1) == 0)

# 9. Field coverage
fc = read_json(STRUCTURED_DIR / 'batch3_run4_field_coverage.json')
check("field_coverage_exists", "batch3_run4" in fc.get("report_id", ""))

# 10. Schema coverage
sc = read_json(STRUCTURED_DIR / 'batch3_run4_schema_coverage.json')
check("schema_non_china", sc.get("non_china_equity_timeseries_excluded") is True)
check("schema_china", sc.get("china_a_h_equity_timeseries_allowed") is True)

# 11. QA
qa = read_json(LOCAL_RUNTIME / 'qa' / f'batch3_run4_qa_summary_{RUN_DATE}.json')
check("qa_exists", "batch3_run4" in qa.get("qa_id", ""))
check("qa_status", qa.get("overall_status") == "passed_with_warnings")
check("qa_tna_blocked", qa["checks"].get("tna_enf_blocked") is True)
check("qa_trusted", qa["checks"].get("trusted_consumption") is False)

# 12. Failure log / Retry / Manifest / Checkpoint
check("failure_log", read_json(STATE_DIR / 'batch3_run4_failure_log.json').get("log_id") is not None)
check("retry_queue", read_json(STATE_DIR / 'batch3_run4_retry_queue.json').get("queue_id") is not None)
check("manifest", read_json(LOCAL_RUNTIME / 'manifest' / f'batch3_run4_manifest_{RUN_DATE}.json').get("manifest_id") is not None)
check("checkpoint", read_json(LOCAL_RUNTIME / 'batch3_run4' / 'batch3_run4_checkpoint.json').get("checkpoint_id") is not None)

# 13. Run state
rs = read_json(STATE_DIR / 'run_state.json')
check("run_state_batch3_run4", rs.get("batch3_run4_completed") is True)
check("next_step", rs.get("next_step") == "batch3_run5_or_incremental_or_time_series_size_collection")

# 14. API stats
cp = read_json(LOCAL_RUNTIME / 'batch3_run4' / 'batch3_run4_checkpoint.json')
check("api_calls_made", cp.get("api_calls_made", 0) > 0)
check("api_failed_ok", cp.get("api_failed", 0) < cp.get("api_calls_made", 1))

print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0: sys.exit(1)
