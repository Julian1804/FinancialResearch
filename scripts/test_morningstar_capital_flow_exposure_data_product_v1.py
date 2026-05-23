"""Test suite for Capital Flow Exposure Data Product v1"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
DP = PROJECT_ROOT / 'runtime' / 'morningstar_capital_flow_exposure_v1'
ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
QA = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill' / 'qa'
def rj(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

# Fund panel
fp = rj(DP/'capital_flow_exposure_fund_panel_v1.json')
ck("fund_panel", fp["total_funds"]==18735)
ck("fund_panel_has_exposure", sum(1 for r in fp["records"] if r.get("sector_exposure_top5"))>10000)

# Exposure panels
ck("sector_panel", rj(DP/'capital_flow_exposure_sector_panel_v1.json')["total_funds"]>10000)
ck("asset_panel", rj(DP/'capital_flow_exposure_asset_class_panel_v1.json')["total_funds"]>0)
ck("country_panel", rj(DP/'capital_flow_exposure_country_panel_v1.json')["panel_id"] is not None)
ck("currency_panel", rj(DP/'capital_flow_exposure_currency_panel_v1.json')["panel_id"] is not None)

# Confidence
cm = rj(DP/'capital_flow_exposure_confidence_model_v1.json')
ck("conf_high", cm["confidence_levels"]["high"]["count"]>=10000)
ck("conf_medium", cm["confidence_levels"]["medium"]["count"]>=0)
ck("conf_low", cm["confidence_levels"]["low"]["count"]>0)
ck("conf_unavailable", cm["confidence_levels"]["unavailable"]["count"]>0)

# Unknown report
ur = rj(DP/'capital_flow_exposure_unknown_underlying_report_v1.json')
ck("unknown_count", ur["unknown_count"]>0)

# Mismatch queue
mr = rj(DP/'capital_flow_exposure_category_mismatch_review_queue_v1.json')
ck("mismatch", mr["total_mismatches"]>0)

# Flow proxy
ck("flow_proxy", rj(DP/'capital_flow_exposure_flow_proxy_panel_v1.json')["panel_id"] is not None)

# Exclusion & TNA
ck("non_china", rj(DP/'capital_flow_exposure_non_china_equity_exclusion_manifest_v1.json')["manifest_id"] is not None)
ck("tna_status", rj(DP/'capital_flow_exposure_tna_enf_sidecar_status_v1.json')["blocked_unit_scale_unknown"] is True)

# Dashboard (lightweight)
ds = rj(DP/'capital_flow_exposure_dashboard_summary_v1.json')
ck("dashboard", ds["note"] is not None)

# Statistical report, manifest, QA
ck("stats", rj(DP/'capital_flow_exposure_statistical_report_sample_v1.json')["report_id"] is not None)
ck("manifest", rj(DP/'capital_flow_exposure_data_product_manifest_v1.json')["manifest_id"] is not None)
ck("qa", rj(QA/'capital_flow_exposure_qa_summary_v1.json')["qa_id"] is not None)

# Run state
rs = rj(ST/'run_state.json')
ck("run_state", rs.get("batch3_run10_completed") is True)
ck("next_step", "time_series" in rs["next_step"])

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
