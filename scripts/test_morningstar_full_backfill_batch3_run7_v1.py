"""Test suite for Morningstar Batch 3 Run 7"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'; STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
LN = LOCAL_RUNTIME / 'batch3_run7'
def rj(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

fi=rj(LN/'batch3_run7_exposure_field_inventory.json'); ck("field_inventory",fi["report_id"] is not None)
sm=rj(LN/'batch3_run7_exposure_semantic_field_map.json'); ck("semantic_map",len(sm["groups"])>=8)
st=rj(LN/'batch3_run7_sector_taxonomy_mapping.json'); ck("taxonomy",len(st["mappings"])>=15)
er=rj(LN/'batch3_run7_direction_evidence_rules.json'); ck("rules","flow_proxy_ready" in er["tiers"])

rc=rj(LN/'batch3_run7_observability_reclassification.json')
ck("reclass_holdings_demoted",rc["holdings_no_longer_mandatory"] is True)
ck("reclass_nav_demoted",rc["nav_returns_demoted"] is True)

fp=rj(LN/'batch3_run7_flow_proxy_ready_universe.json'); ck("flow_ready",fp["total"]==11752)
ca=rj(LN/'batch3_run7_capital_allocation_observable_universe.json'); ck("cap_alloc",ca["total"]==0)
do=rj(LN/'batch3_run7_direction_observable_universe.json'); ck("dir_obs",do["total"]==6983)
mo=rj(LN/'batch3_run7_metadata_only_universe.json'); ck("meta_only",mo["total"]==3324)

es=rj(LN/'batch3_run7_exposure_summary.json')
ck("exposure_summary",es["report_id"] is not None)
ck("exposure_holdings_missing",es["holdings_missing_direction_available"]>0)

ck("sector_summary",rj(LN/'batch3_run7_sector_industry_summary.json')["report_id"] is not None)
ck("country_summary",rj(LN/'batch3_run7_country_region_summary.json')["report_id"] is not None)
ck("asset_summary",rj(LN/'batch3_run7_asset_class_summary.json')["report_id"] is not None)
ck("currency_summary",rj(LN/'batch3_run7_currency_summary.json')["report_id"] is not None)
ck("sec_type_summary",rj(LN/'batch3_run7_security_type_summary.json')["report_id"] is not None)

qa=rj(LOCAL_RUNTIME/'qa'/'batch3_run7_qa_summary_20260523.json')
ck("qa_status",qa["overall_status"]=="passed_with_warnings")
ck("qa_holdings_demoted",qa["checks"]["holdings_demoted"] is True)
ck("qa_nav_demoted",qa["checks"]["nav_returns_demoted"] is True)
ck("qa_tna_blocked",qa["checks"]["tna_blocked"] is True)
ck("qa_non_china",qa["checks"]["non_china_excluded"] is True)

ck("manifest",rj(LOCAL_RUNTIME/'manifest'/'batch3_run7_manifest_20260523.json')["manifest_id"] is not None)

rs=rj(STATE_DIR/'run_state.json')
ck("run_state_run7",rs.get("batch3_run7_completed") is True)
ck("next_step",rs["next_step"]=="batch3_run8_or_flow_proxy_computation")

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
