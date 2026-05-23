"""Test suite for Capital Flow Time-Series Readiness v1"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
TS = PROJECT_ROOT / 'runtime' / 'morningstar_capital_flow_time_series_v1'
ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
def rj(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

ck("readiness",rj(TS/'capital_flow_time_series_readiness_v1.json')["status"] is not None)
ck("size_feasibility",rj(TS/'size_history_feasibility_report_v1.json')["historical_size_available"]==0)
ck("size_inv",rj(TS/'size_field_inventory_v1.json')["report_id"] is not None)
ck("snapshot",rj(TS/'size_snapshot_history_panel_v1.json')["total_snapshots"]>10000)
ck("nav_align",rj(TS/'nav_returns_alignment_panel_v1.json')["total"]==18735)

fc = rj(TS/'flow_proxy_feasibility_classification_v1.json')
ck("fp_class_total",fc["total"]==18735)
ck("fp_class_B",fc["classification_counts"].get("B_trackable_from_now",0)==10309)
ck("fp_class_C",fc["classification_counts"].get("C_capital_allocation",0)==0)
ck("fp_class_D",fc["classification_counts"].get("D_exposure_only",0)==276)
ck("fp_class_E",fc["classification_counts"].get("E_metadata_only",0)==8150)

ck("cap_alloc_univ",rj(TS/'capital_allocation_only_universe_v1.json')["universe_id"] is not None)
ck("exposure_univ",rj(TS/'exposure_only_universe_v1.json')["total"]==276)
ck("meta_univ",rj(TS/'metadata_only_universe_v1.json')["total"]==8150)

ck("methodology",rj(TS/'flow_proxy_methodology_v1.json')["proxy_not_actual_flow"] is True)
ck("calculable",rj(TS/'flow_proxy_calculable_sample_v1.json')["total"]==0)
ck("scheduler",rj(TS/'snapshot_scheduler_plan_v1.json')["report_id"] is not None)
ck("exposure_version",rj(TS/'exposure_versioning_policy_v1.json')["report_id"] is not None)
ck("dashboard",rj(TS/'capital_flow_time_series_dashboard_summary_v1.json')["report_id"] is not None)
ck("qa",rj(PROJECT_ROOT/'runtime'/'morningstar_full_backfill'/'qa'/'capital_flow_time_series_qa_summary_v1.json')["overall_status"]=="passed_with_warnings")

rs = rj(ST/'run_state.json')
ck("run_state",rs.get("batch3_run11_completed") is True)
ck("next_step","token" in rs["next_step"])

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
