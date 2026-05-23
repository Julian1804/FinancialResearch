"""Test suite for Morningstar Batch 3 Run 5"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'; STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260523'; STRUCTURED_DIR = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / RUN_DATE / 'batch3_run5'
def read_json(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def check(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

univ=read_json(LOCAL_RUNTIME/'batch3_run5'/'batch3_run5_expanded_universe.json')
check("universe_exists","batch3_run5" in univ.get("universe_id",""))
check("universe_expanded",univ["total_candidates"]>12951)
check("universe_exact",univ["total_candidates"]==18735)

inv=read_json(STRUCTURED_DIR/'batch3_run5_investment_data_panel.json')
check("inv_panel","batch3_run5" in inv["panel_id"])
check("inv_records",inv["total_records"]>=18000)

ret=read_json(STRUCTURED_DIR/'batch3_run5_returns_panel.json')
check("returns_panel","batch3_run5" in ret["panel_id"])
check("returns_records",ret["total_records"]>0)

hold=read_json(STRUCTURED_DIR/'batch3_run5_holdings_panel.json')
check("holdings_panel","batch3_run5" in hold["panel_id"])
check("holdings_records",hold["total_records"]>0)

ue=read_json(STRUCTURED_DIR/'batch3_run5_underlying_entity_panel.json')
check("ue_panel","batch3_run5" in ue["panel_id"])
check("ue_entities",ue["total_entities"]>0)
check("non_china_shell",all(e["timeseries_policy"]=="entity_shell_only" for e in ue["records"] if not e["is_china_equity"]))

fp=read_json(STRUCTURED_DIR/'batch3_run5_flow_proxy_panel.json')
check("fp_panel","batch3_run5" in fp["panel_id"])
check("fp_records",fp["total_records"]>=18000)
check("fp_is_proxy",all(r["is_proxy_not_actual_flow"] for r in fp["records"]))

tna=read_json(STRUCTURED_DIR/'batch3_run5_tna_enf_sidecar_summary.json')
check("tna_exists","batch3_run5" in tna["summary_id"])
check("tna_blocked",tna["blocked_unit_scale_unknown"] is True)

ex=read_json(LOCAL_RUNTIME/'batch3_run5'/'batch3_run5_non_china_equity_exclusion_manifest.json')
check("exclusion_non_china",ex["exclusion_rules"]["non_china_excluded"] is True)
check("exclusion_china",ex["exclusion_rules"]["china_a_h_allowed"] is True)

ded=read_json(STRUCTURED_DIR/'batch3_run5_dedupe_report.json')
check("dedupe_conflict",ded["conflict"]==0)

fc=read_json(STRUCTURED_DIR/'batch3_run5_field_coverage.json'); check("fc_exists","batch3_run5" in fc["report_id"])
sc=read_json(STRUCTURED_DIR/'batch3_run5_schema_coverage.json')
check("sc_non_china",sc["non_china_equity_timeseries_excluded"] is True)
check("sc_china",sc["china_a_h_equity_timeseries_allowed"] is True)

qa=read_json(LOCAL_RUNTIME/'qa'/f'batch3_run5_qa_summary_{RUN_DATE}.json')
check("qa_status",qa["overall_status"]=="passed_with_warnings")
check("qa_tna_blocked",qa["checks"]["tna_enf_blocked"] is True)
check("qa_trusted",qa["checks"]["trusted_consumption"] is False)

check("failure_log",read_json(STATE_DIR/'batch3_run5_failure_log.json')["log_id"] is not None)
check("retry_queue",read_json(STATE_DIR/'batch3_run5_retry_queue.json')["queue_id"] is not None)
check("manifest",read_json(LOCAL_RUNTIME/'manifest'/f'batch3_run5_manifest_{RUN_DATE}.json')["manifest_id"] is not None)

cp=read_json(LOCAL_RUNTIME/'batch3_run5'/'batch3_run5_checkpoint.json')
check("checkpoint",cp["checkpoint_id"] is not None)
check("api_calls",cp["api_calls_made"]>0)
check("api_failed",cp["api_failed"]==0)

rs=read_json(STATE_DIR/'run_state.json')
check("run_state_run5",rs.get("batch3_run5_completed") is True)
check("next_step",rs["next_step"] in ("batch3_run6_or_incremental_or_time_series_size","batch3_run7_or_incremental_or_time_series"))

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
