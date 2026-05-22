"""Test suite for Morningstar Batch 3 Run 3"""
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260523'
STRUCTURED_DIR = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / RUN_DATE / 'batch3_run3'

def read_json(path):
    assert path.exists(), f"Missing file: {path}"
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        print(f"PASS: {name}")
        passed += 1
    else:
        print(f"FAIL: {name}")
        failed += 1

# 1. Universe
univ = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_expanded_universe.json')
check("universe_exists", univ.get("universe_id") == "morningstar_production_backfill_universe_batch3_run3_v1")
check("universe_has_candidates", univ.get("total_candidates", 0) >= 5000)

# 2. Universe expansion report
uer = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_universe_expansion_report.json')
check("expansion_report_exists", uer.get("report_id") == "batch3_run3_universe_expansion_report_v1")
check("expansion_new_candidates", uer.get("run3_new_candidates", 0) > 0)

# 3. Investment data panel
inv = read_json(STRUCTURED_DIR / 'batch3_run3_investment_data_panel.json')
check("inv_panel_exists", inv.get("panel_id") == "batch3_run3_investment_data_panel_v1")
check("inv_panel_records", inv.get("total_records", 0) >= 5000)

# 4. Size/NAV panel
snav = read_json(STRUCTURED_DIR / 'batch3_run3_size_nav_panel.json')
check("size_nav_panel_exists", snav.get("panel_id") == "batch3_run3_size_nav_panel_v1")
check("size_nav_records", snav.get("total_records", 0) >= 5000)

# 5. Returns panel
ret = read_json(STRUCTURED_DIR / 'batch3_run3_returns_panel.json')
check("returns_panel_exists", ret.get("panel_id") == "batch3_run3_returns_panel_v1")
check("returns_records", ret.get("total_records", 0) > 0)

# 6. Holdings panel
hold = read_json(STRUCTURED_DIR / 'batch3_run3_holdings_panel.json')
check("holdings_panel_exists", hold.get("panel_id") == "batch3_run3_holdings_panel_v1")
check("holdings_records", hold.get("total_records", 0) > 0)

# 7. Underlying entity panel
ue = read_json(STRUCTURED_DIR / 'batch3_run3_underlying_entity_panel.json')
check("underlying_panel_exists", ue.get("panel_id") == "batch3_run3_underlying_entity_panel_v1")
check("underlying_entities_count", ue.get("total_entities", 0) > 0)
check("non_china_equity_shell_only", all(
    e.get("timeseries_policy") == "entity_shell_only" for e in ue.get("records", []) if not e.get("is_china_equity")
))

# 8. Flow Proxy panel
fp = read_json(STRUCTURED_DIR / 'batch3_run3_flow_proxy_panel.json')
check("flow_proxy_exists", fp.get("panel_id") == "batch3_run3_flow_proxy_panel_v1")
check("flow_proxy_records", fp.get("total_records", 0) >= 5000)
check("flow_proxy_is_proxy", all(r.get("is_proxy_not_actual_flow") for r in fp.get("records", [])))

# 9. TNA/ENF sidecar
tna = read_json(STRUCTURED_DIR / 'batch3_run3_tna_enf_sidecar_summary.json')
check("tna_enf_exists", tna.get("summary_id") == "batch3_run3_tna_enf_sidecar_summary_v1")
check("tna_enf_blocked", tna.get("blocked_unit_scale_unknown") is True)

# 10. Non-China equity exclusion
excl = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_non_china_equity_exclusion_manifest.json')
check("exclusion_manifest_exists", excl.get("manifest_id") is not None)
check("exclusion_non_china", excl["exclusion_rules"].get("non_china_equity_timeseries_excluded") is True)
check("exclusion_china_allowed", excl["exclusion_rules"].get("china_a_h_equity_timeseries_allowed") is True)

# 11. Crosswalk update
cw = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_entity_crosswalk_update.json')
check("crosswalk_exists", "batch3_run3_entity_crosswalk_update_v1" in cw.get("update_id", ""))

# 12. Dedupe report
dedupe = read_json(STRUCTURED_DIR / 'batch3_run3_dedupe_report.json')
check("dedupe_exists", dedupe.get("report_id") == "batch3_run3_dedupe_report_v1")
check("dedupe_conflict", dedupe.get("conflict", -1) == 0)

# 13. Field coverage
fc = read_json(STRUCTURED_DIR / 'batch3_run3_field_coverage.json')
check("field_coverage_exists", fc.get("report_id") == "batch3_run3_field_coverage_v1")
check("field_coverage_fund_size", fc["fields"]["fund_size"]["available"] > 0)

# 14. Schema coverage
sc = read_json(STRUCTURED_DIR / 'batch3_run3_schema_coverage.json')
check("schema_coverage_exists", sc.get("report_id") == "batch3_run3_schema_coverage_v1")
check("schema_non_china_excluded", sc.get("non_china_equity_timeseries_excluded") is True)
check("schema_china_allowed", sc.get("china_a_h_equity_timeseries_allowed") is True)

# 15. QA
qa = read_json(LOCAL_RUNTIME / 'qa' / f'batch3_run3_qa_summary_{RUN_DATE}.json')
check("qa_exists", qa.get("qa_id") == "batch3_run3_qa_summary_v1")
check("qa_status", qa.get("overall_status") == "passed_with_warnings")
check("qa_non_china_excluded", qa["checks"].get("non_china_equity_timeseries_excluded") is True)
check("qa_china_allowed", qa["checks"].get("china_a_h_equity_timeseries_allowed") is True)
check("qa_tna_blocked", qa["checks"].get("tna_enf_blocked") is True)
check("qa_formal_false", qa["checks"].get("formal_trusted_consumption_enabled") is False)
check("qa_parse_lab_ok", qa["checks"].get("parse_lab_affected") is False)

# 16. Failure log
fl = read_json(STATE_DIR / 'batch3_run3_failure_log.json')
check("failure_log_exists", fl.get("log_id") == "batch3_run3_failure_log_v1")

# 17. Retry queue
rq = read_json(STATE_DIR / 'batch3_run3_retry_queue.json')
check("retry_queue_exists", rq.get("queue_id") == "batch3_run3_retry_queue_v1")

# 18. Manifest
mf = read_json(LOCAL_RUNTIME / 'manifest' / f'batch3_run3_manifest_{RUN_DATE}.json')
check("manifest_exists", mf.get("manifest_id") == "batch3_run3_manifest_v1")

# 19. Checkpoint
cp = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_checkpoint.json')
check("checkpoint_exists", cp.get("checkpoint_id", "").startswith("checkpoint_after_batch3_run3_"))

# 20. Run state
rs = read_json(STATE_DIR / 'run_state.json')
check("run_state_batch3_run3_completed", rs.get("batch3_run3_completed") is True)
check("run_state_next_step", rs.get("next_step") == "batch3_run4_or_incremental_or_time_series_deepening")
check("run_state_boundary", rs.get("equity_timeseries_boundary", {}).get("non_china_equity_timeseries_excluded") is True)

# 21. Next run plan
plan = read_json(LOCAL_RUNTIME / 'batch3_run3' / 'batch3_run3_next_run_plan.json')
check("next_plan_exists", plan.get("plan_id") == "batch3_run3_next_run_plan_v1")

# 22. API stats
check("api_calls_made", cp.get("api_calls_made", 0) > 0)
check("api_calls_failed", cp.get("api_calls_failed", 0) == 0)
check("investment_data_backfilled", cp["records"].get("investment_data_total", 0) >= 5000)
check("returns_backfilled", cp["records"].get("returns_total", 0) > 100000)
check("holdings_backfilled", cp["records"].get("holdings", 0) > 1000000)

print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0:
    sys.exit(1)
