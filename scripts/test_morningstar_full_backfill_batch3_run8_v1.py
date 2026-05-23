"""Test suite for Morningstar Batch 3 Run 8"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
LR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'; ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
LN = LR / 'batch3_run8'
def rj(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

# Core files
ck("rules",rj(LN/'batch3_run8_direction_evidence_rules.json')["report_id"] is not None)
ck("taxonomy",rj(LN/'batch3_run8_sector_taxonomy_mapping.json')["report_id"] is not None)
ck("panel",rj(LN/'batch3_run8_direction_evidence_panel.json')["total"]==22059)
ck("confidence",rj(LN/'batch3_run8_direction_confidence_report.json')["report_id"] is not None)
ck("reclass",rj(LN/'batch3_run8_observability_reclassification.json')["report_id"] is not None)

# Tier counts
ck("flow_ready",rj(LN/'batch3_run8_flow_proxy_ready_universe.json')["total"]==11446)
ck("cap_alloc",rj(LN/'batch3_run8_capital_allocation_observable_universe.json')["total"]==0)
ck("dir_obs",rj(LN/'batch3_run8_direction_observable_universe.json')["total"]==6045)
ck("weak_hint",rj(LN/'batch3_run8_weak_direction_hint_universe.json')["total"]==4545)
ck("meta",rj(LN/'batch3_run8_metadata_only_universe.json')["total"]==23)
ck("sidecar",rj(LN/'batch3_run8_sidecar_flow_like_universe.json')["total"]==0)

# Evidence levels
cr = rj(LN/'batch3_run8_direction_confidence_report.json')
ck("L1_holdings",cr["L1_holdings"]==11249)
ck("L3_specific",cr["L3_specific_category"]==6242)
ck("reliable_dir",cr["reliable_direction"]==11249+6242)

# Downgrade reports
ck("broad_downgrade",rj(LN/'batch3_run8_broad_category_exclusion_report.json')["downgraded_count"]==589)
ck("country_downgrade",rj(LN/'batch3_run8_country_only_bias_warning.json')["downgraded_count"]==1631)
ck("name_downgrade",rj(LN/'batch3_run8_name_based_direction_warning.json')["downgraded_count"]==2325)

# Summaries
ck("sector",rj(LN/'batch3_run8_sector_industry_summary.json')["report_id"] is not None)
ck("country",rj(LN/'batch3_run8_country_region_summary.json')["report_id"] is not None)
ck("asset",rj(LN/'batch3_run8_asset_class_summary.json')["report_id"] is not None)
ck("currency",rj(LN/'batch3_run8_currency_summary.json')["report_id"] is not None)

# QA
qa = rj(LR/'qa'/'batch3_run8_qa_summary_20260523.json')
ck("qa_status",qa["overall_status"]=="passed_with_warnings")
ck("qa_broad_excluded",qa["checks"]["broad_categories_excluded"] is True)
ck("qa_country_demoted",qa["checks"]["country_demoted"] is True)
ck("qa_currency_excluded",qa["checks"]["base_currency_excluded"] is True)
ck("qa_nav_flow_only",qa["checks"]["nav_returns_not_hard_requirement"] is True)
ck("qa_tna_blocked",qa["checks"]["tna_blocked"] is True)
ck("qa_non_china",qa["checks"]["non_china_excluded"] is True)

# Manifest
ck("manifest",rj(LR/'manifest'/'batch3_run8_manifest_20260523.json')["manifest_id"] is not None)

# Run state
rs = rj(ST/'run_state.json')
ck("run_state",rs.get("batch3_run8_completed") is True)
ck("next_step",rs["next_step"] in ("batch3_run9_or_flow_proxy_computation","batch3_run10_or_flow_proxy_computation"))

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
