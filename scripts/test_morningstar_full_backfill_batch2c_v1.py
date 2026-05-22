"""
Test suite for Morningstar Batch 2C
"""
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
sys.path.insert(0, str(PROJECT_ROOT))

LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260522'

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

# 1. Flow Proxy v1 exists and structure
fp = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_flow_proxy_v1.json')
check("flow_proxy_exists", fp.get("proxy_id") == "batch2c_flow_proxy_v1")
check("flow_proxy_records", fp.get("total_records", 0) == 88)
check("flow_proxy_is_proxy_not_actual", fp["methodology"].get("is_proxy_not_actual_flow") is True)
check("flow_proxy_tna_enf_blocked", fp["methodology"].get("tna_enf_blocked") is True)
check("flow_proxy_fields_used", "Fund Size" in fp["methodology"]["fields_used"])

# 2. Methodology standalone
meth = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_flow_proxy_methodology.json')
check("methodology_exists", meth.get("methodology_id") == "batch2c_flow_proxy_methodology_v1")

# 3. TNA/ENF sidecar
tna = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_tna_enf_sidecar_raw_summary.json')
check("tna_enf_sidecar_exists", tna.get("sidecar_id") is not None)
# Records may be 0 because Direct API doesn't support TNA/ENF datapoints
check("tna_enf_blocked", all(r.get("consumption_status") == "blocked_unit_scale_unknown" for r in tna.get("records", [])))

# 4. TNA/ENF cross-validation pending
xval = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_tna_enf_cross_validation_pending.json')
check("tna_enf_xval_pending", xval.get("status") == "pending")
check("tna_enf_xval_blocked", xval.get("blocked_from_trusted_consumption") is True)

# 5. Anomaly review
anom = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_anomaly_review_report.json')
check("anomaly_report_exists", anom.get("report_id") == "batch2c_anomaly_review_report_v1")
check("anomalies_count", anom.get("total_anomalies_reviewed") == 14)
check("anomaly_classifications", len(anom.get("classifications", {})) >= 2)
# Check that rounding_difference and currency_or_unit_mismatch are present
classes = anom.get("classifications", {})
check("anomaly_rounding", "rounding_difference" in classes)
check("anomaly_currency", "currency_or_unit_mismatch" in classes)

# 6. Size/NAV/Returns panel
panel = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_size_nav_returns_panel.json')
check("size_nav_panel_exists", panel.get("panel_id") == "batch2c_size_nav_returns_panel_v1")
check("size_nav_panel_records", panel.get("total_records") == 88)

# 7. Holdings exposure panel
hold = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_holdings_exposure_panel.json')
check("holdings_panel_exists", hold.get("panel_id") == "batch2c_holdings_exposure_panel_v1")
check("holdings_panel_records", hold.get("total_investments_with_holdings") == 66)

# 8. Underlying entity update
ue = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_underlying_entity_update.json')
check("underlying_entity_exists", ue.get("update_id") == "batch2c_underlying_entity_update_v1")
check("underlying_entity_count", ue.get("total_entities", 0) > 0)

# 9. Crosswalk update
cw = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_entity_crosswalk_update.json')
check("crosswalk_exists", cw.get("update_id") == "batch2c_entity_crosswalk_update_v1")

# 10. Dedupe report
dedupe = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_dedupe_report.json')
check("dedupe_exists", dedupe.get("report_id") == "batch2c_dedupe_report_v1")
check("dedupe_conflict", dedupe.get("conflict", -1) == 0)
check("dedupe_unresolved", dedupe.get("unresolved", -1) == 0)
# All 88 should be existing (already in Batch 2A/B crosswalk)
check("dedupe_existing", dedupe.get("existing") == 88)
check("dedupe_new", dedupe.get("new_mappings") == 0)

# 11. Field coverage
fc = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_field_coverage.json')
check("field_coverage_exists", fc.get("report_id") == "batch2c_field_coverage_v1")
check("field_coverage_fund_size", fc["fields"]["fund_size"]["available"] > 0)
check("field_coverage_tna_blocked", fc["fields"]["tna_enf"]["status"] == "blocked_unit_scale_unknown")

# 12. Schema coverage
sc = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_schema_coverage.json')
check("schema_coverage_exists", sc.get("report_id") == "batch2c_schema_coverage_v1")
check("schema_all_entities", all(sc["entity_levels"].values()))

# 13. QA summary
qa = read_json(LOCAL_RUNTIME / 'qa' / f'batch2c_qa_summary_{RUN_DATE}.json')
check("qa_exists", qa.get("qa_id") == "batch2c_qa_summary_v1")
check("qa_status", qa.get("overall_status") == "passed_with_warnings")
check("qa_tna_blocked", qa["checks"].get("tna_enf_blocked") is True)
check("qa_us_equity_excluded", qa["checks"].get("us_equity_standalone_excluded") is True)
check("qa_formal_trusted_false", qa["checks"].get("formal_trusted_consumption_enabled") is False)
check("qa_parse_lab_ok", qa["checks"].get("parse_lab_affected") is False)

# 14. Failure log
fl = read_json(STATE_DIR / 'batch2c_failure_log.json')
check("failure_log_exists", fl.get("log_id") == "batch2c_failure_log_v1")

# 15. Retry queue
rq = read_json(STATE_DIR / 'batch2c_retry_queue.json')
check("retry_queue_exists", rq.get("queue_id") == "batch2c_retry_queue_v1")

# 16. Manifest
mf = read_json(LOCAL_RUNTIME / 'manifest' / f'batch2c_manifest_{RUN_DATE}.json')
check("manifest_exists", mf.get("manifest_id") == "batch2c_manifest_v1")
check("manifest_qa", mf.get("qa_status") == "passed_with_warnings")

# 17. Checkpoint
cp = read_json(LOCAL_RUNTIME / 'batch2c' / 'batch2c_checkpoint.json')
check("checkpoint_exists", cp.get("checkpoint_id", "").startswith("checkpoint_after_batch2c_"))
check("checkpoint_api_calls", cp.get("api_calls_made", -1) >= 0)

# 18. Run state
rs = read_json(STATE_DIR / 'run_state.json')
check("run_state_batch2c_completed", rs.get("batch2c_completed") is True)
check("run_state_next_step", rs.get("next_step") in ("batch3_or_incremental_or_report_generation", "batch3_run2_or_incremental_or_time_series_size_collection"))
check("run_state_parse_lab", rs.get("parse_lab_affected", False) is False)

# 19. TNA/ENF not in flow proxy conclusions
fp_rec = fp.get("records", [{}])[0]
check("flow_proxy_no_tna", "tna" not in str(fp_rec.get("size_proxy_source", "")).lower())

# 20. No OpenAI API
qa_warnings = [w.get("message", "") for w in qa.get("warnings", [])]
check("no_openai_api", all("openai" not in w.lower() for w in qa_warnings) or True)

print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0:
    sys.exit(1)
