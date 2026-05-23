"""Test suite for Morningstar Batch 3 Run 6"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'; STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260523'; STRUCTURED_DIR = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / RUN_DATE / 'batch3_run6'
def read_json(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def check(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

univ=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_expanded_universe.json')
check("universe_exists","batch3_run6" in univ.get("universe_id",""))
check("universe_expanded",univ["total_candidates"]>18735)
check("universe_exact",univ["total_candidates"]==22059)

inv=read_json(STRUCTURED_DIR/'batch3_run6_investment_data_panel.json')
check("inv_panel","batch3_run6" in inv["panel_id"])
check("inv_records",inv["total_records"]>=22000)

ret=read_json(STRUCTURED_DIR/'batch3_run6_returns_panel.json')
check("returns_exists","batch3_run6" in ret["panel_id"])

hold=read_json(STRUCTURED_DIR/'batch3_run6_holdings_panel.json')
check("holdings_exists","batch3_run6" in hold["panel_id"])

ue=read_json(STRUCTURED_DIR/'batch3_run6_underlying_entity_panel.json')
check("ue_exists","batch3_run6" in ue["panel_id"])

fp=read_json(STRUCTURED_DIR/'batch3_run6_flow_proxy_panel.json')
check("fp_exists","batch3_run6" in fp["panel_id"])
check("fp_records",fp["total_records"]>=22000)
check("fp_is_proxy",all(r["is_proxy_not_actual_flow"] for r in fp["records"]))

tna=read_json(STRUCTURED_DIR/'batch3_run6_tna_enf_sidecar_summary.json')
check("tna_blocked",tna["blocked_unit_scale_unknown"] is True)

ex=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_non_china_equity_exclusion_manifest.json')
check("exclusion_non_china",ex["exclusion_rules"]["non_china_excluded"] is True)

ded=read_json(STRUCTURED_DIR/'batch3_run6_dedupe_report.json')
check("dedupe_conflict",ded["conflict"]==0)

fc=read_json(STRUCTURED_DIR/'batch3_run6_field_coverage.json'); check("fc","batch3_run6" in fc["report_id"])
sc=read_json(STRUCTURED_DIR/'batch3_run6_schema_coverage.json'); check("sc_non_china",sc["non_china_equity_timeseries_excluded"] is True)

qa=read_json(LOCAL_RUNTIME/'qa'/f'batch3_run6_qa_summary_{RUN_DATE}.json')
check("qa_status",qa["overall_status"]=="passed_with_warnings")
check("qa_trusted",qa["checks"]["trusted_consumption"] is False)

check("failure_log",read_json(STATE_DIR/'batch3_run6_failure_log.json')["log_id"] is not None)
check("manifest",read_json(LOCAL_RUNTIME/'manifest'/f'batch3_run6_manifest_{RUN_DATE}.json')["manifest_id"] is not None)
check("checkpoint",read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_checkpoint.json')["checkpoint_id"] is not None)
check("method_inventory",read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_method_inventory.json')["report_id"] is not None)
check("source_audit",read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_universe_source_audit.json')["report_id"] is not None)

rs=read_json(STATE_DIR/'run_state.json')
check("run_state_run6",rs.get("batch3_run6_completed") is True)
check("next_step",rs["next_step"] in ("batch3_run7_or_incremental_or_time_series","batch3_run8_or_flow_proxy_computation","batch3_run9_or_flow_proxy_computation"))
# Observability classification checks
hi=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_high_observability_universe.json')
check("high_obs_exists","high_observability" in hi["universe_id"])
check("high_obs_count", hi["total"] == 10964)
med=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_medium_observability_universe.json')
check("med_obs_count", med["total"] == 1073)
low=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_low_observability_universe.json')
check("low_obs_count", low["total"] == 6698)
meta=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_metadata_only_candidates.json')
check("meta_count", meta["total"] == 3324)
obs=read_json(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_observability_classification.json')
check("obs_report_exists", obs["report_id"] is not None)
check("triple_coverage", obs["triple_coverage"]["all_three_simultaneously"] == 10964)

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
