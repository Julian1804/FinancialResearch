"""Test suite for Morningstar Batch 3 Run 9"""
import json, sys
from pathlib import Path
PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch'); sys.path.insert(0, str(PROJECT_ROOT))
LR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'; ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
LN = LR / 'batch3_run9'
def rj(p):
    assert p.exists(), f"Missing: {p}"
    return json.load(open(p,'r',encoding='utf-8'))
passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

# Entities
ue = rj(LN/'batch3_run9_underlying_entity_enriched.json')
ck("entities", ue["total"]==237082)
ck("entities_enriched", ue["total"]>200000)

ec = rj(LN/'batch3_run9_underlying_entity_classification_report.json')
ck("classified_sector", ec["classified_sector"]>150000)
ck("classified_asset", ec["classified_asset_class"]>150000)

# Exposure panels
ck("sector_panel", rj(LN/'batch3_run9_sector_exposure_panel.json')["total_funds_with_exposure"]>10000)
ck("asset_panel", rj(LN/'batch3_run9_asset_class_exposure_panel.json')["total_funds_with_exposure"]>10000)
ck("country_panel", rj(LN/'batch3_run9_country_region_exposure_panel.json').get("total_funds_with_exposure",0)>0)
ck("currency_panel", rj(LN/'batch3_run9_currency_exposure_panel.json').get("total_funds_with_exposure",0)>0)
ck("stype_panel", rj(LN/'batch3_run9_security_type_exposure_panel.json').get("total_funds_with_exposure",0)>0)
ck("concentration", rj(LN/'batch3_run9_top_holdings_concentration.json')["total"]>0)
ck("taxonomy", rj(LN/'batch3_run9_sector_taxonomy_mapping.json')["report_id"] is not None)

# Upgrade report
up = rj(LN/'batch3_run9_direction_evidence_upgrade_report.json')
ck("upgrade_funds", up["funds_upgradable_to_L2"]>5000)
ck("upgrade_partial", up["funds_with_partial_exposure"]>0)

# Cross-check
cc = rj(LN/'batch3_run9_category_strategy_crosscheck_report.json')
ck("crosscheck", cc["total_funds_checked"]==11249)

# Quality & exclusion
ck("quality", rj(LN/'batch3_run9_exposure_derivation_quality_report.json')["report_id"] is not None)
ck("non_china", rj(LN/'batch3_run9_non_china_equity_entity_shell_manifest.json')["manifest_id"] is not None)

# QA
qa = rj(LR/'qa'/'batch3_run9_qa_summary_20260523.json')
ck("qa_status", qa["overall_status"]=="passed_with_warnings")
ck("qa_non_china", qa["checks"]["non_china_excluded"] is True)
ck("qa_tna_blocked", qa["checks"]["tna_blocked"] is True)

ck("manifest", rj(LR/'manifest'/'batch3_run9_manifest_20260523.json')["manifest_id"] is not None)

rs = rj(ST/'run_state.json')
ck("run_state", rs.get("batch3_run9_completed") is True)
ck("next_step", rs["next_step"]=="batch3_run10_or_flow_proxy_computation")

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
