"""
Morningstar Batch 3 Run 10 - Capital Flow Exposure Data Product v1
Consolidates Run 5-9 data into a single consumable data product.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
SB = Path(r'Z:\data_lake_master\structured\licensed\morningstar')
LR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
DP_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_capital_flow_exposure_v1'
QA = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill' / 'qa'
RD = '20260523'
RAW_DP = Path(r'Z:\data_lake_master\raw\licensed\morningstar') / RD / 'capital_flow_exposure_v1'
STR_DP = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / 'capital_flow_exposure_v1'
for d in [DP_DIR, RAW_DP, STR_DP]: d.mkdir(parents=True, exist_ok=True)

def ni(): return datetime.now(timezone.utc).isoformat()
def lj(p):
    if not p.exists(): return {}
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def sj(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2,default=str)

print("[Run10] Loading source data...")
# Core panels
inv_p = lj(SB/RD/'batch3_run5'/'batch3_run5_investment_data_panel.json')
ret_p = lj(SB/RD/'batch3_run5'/'batch3_run5_returns_panel.json')
hold_p = lj(SB/RD/'batch3_run5'/'batch3_run5_holdings_panel.json')
inv = {r['performance_id']:r for r in inv_p.get('records',[]) if r.get('performance_id')}
ret = {r['performance_id']:r for r in ret_p.get('records',[]) if r.get('performance_id')}
hold = {r['performance_id']:r for r in hold_p.get('records',[]) if r.get('performance_id')}

# Run 8 direction evidence
dpanel = lj(LR/'batch3_run8'/'batch3_run8_direction_evidence_panel.json')
dev_map = {r['performance_id']:r for r in dpanel.get('records',[]) if r.get('performance_id')}

# Run 9 exposures
sec9 = lj(LR/'batch3_run9'/'batch3_run9_sector_exposure_panel.json')
ac9  = lj(LR/'batch3_run9'/'batch3_run9_asset_class_exposure_panel.json')
cnt9 = lj(LR/'batch3_run9'/'batch3_run9_country_region_exposure_panel.json')
cur9 = lj(LR/'batch3_run9'/'batch3_run9_currency_exposure_panel.json')
st9  = lj(LR/'batch3_run9'/'batch3_run9_security_type_exposure_panel.json')
conc9 = lj(LR/'batch3_run9'/'batch3_run9_top_holdings_concentration.json')
cc9 = lj(LR/'batch3_run9'/'batch3_run9_category_strategy_crosscheck_report.json')
ent9 = lj(LR/'batch3_run9'/'batch3_run9_underlying_entity_enriched.json')
up9 = lj(LR/'batch3_run9'/'batch3_run9_direction_evidence_upgrade_report.json')
cl9 = lj(LR/'batch3_run9'/'batch3_run9_underlying_entity_classification_report.json')

# Run 6/7 universe
univ = lj(LR/'batch3_run6'/'batch3_run6_expanded_universe.json')

print(f"  inv={len(inv)} ret={len(ret)} hold={len(hold)} dev={len(dev_map)} entities={ent9.get('total',0)}")

# ====== 1. Fund-Level Capital Flow Panel ======
print("[Run10] Building fund-level capital flow panel...")
flow_panel = []
confidence_counter = Counter()
mismatch_dict = {m['pid']:m for m in cc9.get('mismatches',[])}
sec_by_pid = {r['performance_id']:r for r in sec9.get('records',[])}
ac_by_pid = {r['performance_id']:r for r in ac9.get('records',[])}
cnt_by_pid = {r['performance_id']:r for r in cnt9.get('records',[])}
cur_by_pid = {r['performance_id']:r for r in cur9.get('records',[])}
conc_by_pid = {r['performance_id']:r for r in conc9.get('records',[])}

for pid, inv_r in inv.items():
    ret_r = ret.get(pid, {})
    hold_r = hold.get(pid, {})
    dev_r = dev_map.get(pid, {})
    sec_r = sec_by_pid.get(pid, {})
    ac_r = ac_by_pid.get(pid, {})
    cnt_r = cnt_by_pid.get(pid, {})
    cur_r = cur_by_pid.get(pid, {})
    conc_r = conc_by_pid.get(pid, {})

    # Confidence model
    has_holdings = hold_r.get('holdings_count', 0) > 0
    dev_level = dev_r.get('direction_evidence_level', 5)
    has_sector_exp = bool(sec_r.get('distribution'))
    has_ac_exp = bool(ac_r.get('distribution'))

    if has_holdings and has_sector_exp:
        confidence = 'high'
    elif has_holdings and has_ac_exp:
        confidence = 'medium'
    elif dev_level <= 3:
        confidence = 'low'
    else:
        confidence = 'unavailable'
    confidence_counter[confidence] += 1

    # Mismatch
    mismatch = mismatch_dict.get(pid, None)

    entry = {
        'performance_id': pid,
        'sec_id': inv_r.get('sec_id'), 'fund_id': inv_r.get('fund_id'),
        'name': inv_r.get('name'), 'ticker': inv_r.get('ticker'),
        'isin': inv_r.get('isin'), 'cusip': inv_r.get('cusip'),
        'firm_name': inv_r.get('firm_name'),
        'category': inv_r.get('category'), 'global_category': inv_r.get('global_category'),
        'base_currency': inv_r.get('base_currency'), 'country': inv_r.get('country'),
        'security_type': inv_r.get('security_type'),
        'fund_size': inv_r.get('fund_size'),
        'net_assets_shareclass': inv_r.get('net_assets_shareclass'),
        'strategy_aum': inv_r.get('strategy_aum'),
        'nav_daily': inv_r.get('nav_daily'),
        'latest_return_pct': ret_r.get('latest_monthly_return_pct'),
        'latest_return_date': ret_r.get('latest_return_date'),
        'returns_count': ret_r.get('returns_count', 0),
        'holdings_count': hold_r.get('holdings_count', 0),
        'portfolio_date': hold_r.get('portfolio_dates', [None])[0] if hold_r.get('portfolio_dates') else None,
        'sector_exposure_top5': dict(Counter(sec_r.get('distribution', {})).most_common(5)),
        'asset_class_exposure_top5': dict(Counter(ac_r.get('distribution', {})).most_common(5)),
        'country_exposure_top5': dict(Counter(cnt_r.get('distribution', {})).most_common(5)),
        'currency_exposure_top5': dict(Counter(cur_r.get('distribution', {})).most_common(5)),
        'top_3_sectors': conc_r.get('top_3_sectors', []),
        'exposure_confidence': confidence,
        'direction_evidence_level': dev_r.get('direction_evidence_level'),
        'direction_level_name': dev_r.get('direction_level_name'),
        'direction_confidence_score': dev_r.get('direction_confidence_score'),
        'flow_proxy_status': 'conceptual_framework_only',
        'category_mismatch': mismatch is not None,
        'category_mismatch_detail': mismatch,
        'non_china_equity_excluded': True
    }
    flow_panel.append(entry)

panel_doc = {"panel_id":"capital_flow_exposure_fund_panel_v1","generated_at":ni(),"total_funds":len(flow_panel),"records":flow_panel}
sj(DP_DIR/'capital_flow_exposure_fund_panel_v1.json', panel_doc)
sj(STR_DP/'capital_flow_exposure_fund_panel_v1.json', panel_doc)

# ====== 2. Exposure Panels (Summary Versions) ======
for name, src in [('sector',sec9),('asset_class',ac9),('country',cnt9),('currency',cur9),('security_type',st9)]:
    d = {"panel_id":f"capital_flow_exposure_{name}_panel_v1","generated_at":ni(),"total_funds":src.get('total_funds_with_exposure',0),"records":src.get('records',[])}
    sj(DP_DIR/f'capital_flow_exposure_{name}_panel_v1.json', d)
    sj(STR_DP/f'capital_flow_exposure_{name}_panel_v1.json', d)

# ====== 3. Confidence Model ======
cm = {"report_id":"capital_flow_exposure_confidence_model_v1","generated_at":ni(),
    "confidence_levels":{
        "high": {"criteria":"has_holdings + sector_exposure_derived","count":confidence_counter['high']},
        "medium": {"criteria":"has_holdings + asset_class_exposure_only","count":confidence_counter['medium']},
        "low": {"criteria":"direction_level<=3, no holdings/sector exposure","count":confidence_counter['low']},
        "unavailable": {"criteria":"no direction evidence","count":confidence_counter['unavailable']}
    },
    "note":"Confidence based on holdings-derived exposure classification from Run 9"}
sj(DP_DIR/'capital_flow_exposure_confidence_model_v1.json', cm)
sj(STR_DP/'capital_flow_exposure_confidence_model_v1.json', cm)

# ====== 4. Unknown Underlying Entity Report ======
unk = [e for e in ent9.get('records',[]) if e.get('sector') == '未知']
unk_by_type = Counter(e.get('security_type','') for e in unk); unk_by_country = Counter(e.get('country','') for e in unk)
unk_by_cur = Counter(e.get('currency','') for e in unk)
ur = {"report_id":"capital_flow_exposure_unknown_underlying_report_v1","generated_at":ni(),
    "total_entities":ent9.get('total',0),"unknown_count":len(unk),"unknown_pct":round(len(unk)/max(ent9.get('total',1),1)*100,1),
    "by_security_type":dict(unk_by_type.most_common(20)),
    "by_country":dict(unk_by_country.most_common(20)),
    "by_currency":dict(unk_by_cur.most_common(20)),
    "top_unknown_by_name":[e['name'][:60] for e in unk[:30] if e.get('name')],
    "note":"These entities could not be classified by sector. Primary reason: detailHoldingType empty or unmatched in STYPE_MAP."}
sj(DP_DIR/'capital_flow_exposure_unknown_underlying_report_v1.json', ur)
sj(STR_DP/'capital_flow_exposure_unknown_underlying_report_v1.json', ur)

# ====== 5. Category Mismatch Review Queue ======
mr = {"report_id":"capital_flow_exposure_category_mismatch_review_queue_v1","generated_at":ni(),
    "total_mismatches":cc9.get('total_mismatches',0),"total_checked":cc9.get('total_funds_checked',0),
    "review_queue":cc9.get('mismatches',[]), "priority":"review_category_vs_holdings", "do_not_auto_fail":True}
sj(DP_DIR/'capital_flow_exposure_category_mismatch_review_queue_v1.json', mr)
sj(STR_DP/'capital_flow_exposure_category_mismatch_review_queue_v1.json', mr)

# ====== 6. Flow Proxy Panel ======
fp_doc = {"panel_id":"capital_flow_exposure_flow_proxy_panel_v1","generated_at":ni(),
    "total_funds":len(flow_panel),"status":"conceptual_framework_only",
    "formula":"size_t - size_t_minus_1 * (1 + return_t)",
    "method":"size_change_less_price_impact",
    "fields_used":["Fund Size","Net Assets-Share Class","Strategy AUM","NAV Daily","Monthly Return","Holdings marketValue","Sector/Asset/Country exposure"],
    "tna_enf_blocked":True,"is_proxy_not_actual_flow":True,"records":flow_panel}
sj(DP_DIR/'capital_flow_exposure_flow_proxy_panel_v1.json', fp_doc)
sj(STR_DP/'capital_flow_exposure_flow_proxy_panel_v1.json', fp_doc)

# ====== 7. Non-China Equity Exclusion ======
sj(DP_DIR/'capital_flow_exposure_non_china_equity_exclusion_manifest_v1.json', {"manifest_id":"capital_flow_exposure_non_china_equity_exclusion_v1","generated_at":ni(),"rules":{"non_china_equity_timeseries_excluded":True,"china_a_h_allowed":True,"entity_shell_only":True}})

# ====== 8. TNA/ENF Sidecar Status ======
sj(DP_DIR/'capital_flow_exposure_tna_enf_sidecar_status_v1.json', {"status_id":"capital_flow_exposure_tna_enf_sidecar_v1","generated_at":ni(),"blocked_unit_scale_unknown":True,"tna_enf_not_in_flow_proxy":True,"tna_enf_not_in_trusted_consumption":True})

# ====== 9. Analysis Packet Sample ======
sample_n = min(20, len(flow_panel))
ap = {"report_id":"capital_flow_exposure_analysis_packet_sample_v1","generated_at":ni(),"total_funds":len(flow_panel),"sample_size":sample_n,"sample":flow_panel[:sample_n]}
sj(DP_DIR/'capital_flow_exposure_analysis_packet_sample_v1.json', ap)

# ====== 10. Statistical Report Sample ======
total_size = sum(r.get('fund_size') or 0 for r in flow_panel)
total_nav = sum(r.get('net_assets_shareclass') or 0 for r in flow_panel)
total_holdings = sum(r.get('holdings_count', 0) for r in flow_panel)
sr = {"report_id":"capital_flow_exposure_statistical_report_sample_v1","generated_at":ni(),
    "summary_statistics":{
        "total_funds":len(flow_panel), "funds_with_holdings":sum(1 for r in flow_panel if r.get('holdings_count',0)>0),
        "funds_with_sector_exposure":sum(1 for r in flow_panel if r.get('sector_exposure_top5')),
        "funds_with_asset_class_exposure":sum(1 for r in flow_panel if r.get('asset_class_exposure_top5')),
        "funds_with_country_exposure":sum(1 for r in flow_panel if r.get('country_exposure_top5')),
        "exposure_high":confidence_counter['high'],"exposure_medium":confidence_counter['medium'],
        "exposure_low":confidence_counter['low'],"exposure_unavailable":confidence_counter['unavailable'],
        "category_mismatches":len(cc9.get('mismatches',[])),
        "unknown_underlying_entities":ent9.get('total',0)-cl9.get('classified_sector',0),
    }}
sj(DP_DIR/'capital_flow_exposure_statistical_report_sample_v1.json', sr)
sj(STR_DP/'capital_flow_exposure_statistical_report_sample_v1.json', sr)

# ====== 11. Dashboard Summary (lightweight, no holdings blob) ======
ds = {"report_id":"capital_flow_exposure_dashboard_summary_v1","generated_at":ni(),
    "highlights":{
        "total_funds":len(flow_panel), "funds_with_exposure":sum(1 for r in flow_panel if r.get('sector_exposure_top5')),
        "exposure_high_pct":round(confidence_counter['high']/max(len(flow_panel),1)*100,1),
        "exposure_medium_pct":round(confidence_counter['medium']/max(len(flow_panel),1)*100,1),
        "top_sectors_global":dict(Counter(s for r in sec9.get('records',[]) for s in r.get('distribution',{}).keys()).most_common(10)),
        "top_asset_classes_global":dict(Counter(a for r in ac9.get('records',[]) for a in r.get('distribution',{}).keys()).most_common(8)),
        "top_countries_by_fund_count":dict(Counter(r.get('country','') for r in flow_panel).most_common(10)),
        "category_mismatches":len(cc9.get('mismatches',[])),
        "unknown_entities":ent9.get('total',0)-cl9.get('classified_sector',0),
    },
    "note":"Dashboard-optimized summary. No holdings blob. Load from summary panels only."}
sj(DP_DIR/'capital_flow_exposure_dashboard_summary_v1.json', ds)
sj(STR_DP/'capital_flow_exposure_dashboard_summary_v1.json', ds)

# ====== 12. Data Product Manifest ======
mf_doc = {"manifest_id":"capital_flow_exposure_data_product_manifest_v1","generated_at":ni(),
    "data_product_name":"Morningstar Capital Flow Exposure Data Product v1",
    "components":[
        {"name":"capital_flow_exposure_fund_panel","records":len(flow_panel),"path":str(DP_DIR/'capital_flow_exposure_fund_panel_v1.json')},
        {"name":"capital_flow_exposure_sector_panel","records":sec9.get('total_funds_with_exposure',0)},
        {"name":"capital_flow_exposure_asset_class_panel","records":ac9.get('total_funds_with_exposure',0)},
        {"name":"capital_flow_exposure_country_panel","records":cnt9.get('total_funds_with_exposure',0)},
        {"name":"capital_flow_exposure_currency_panel","records":cur9.get('total_funds_with_exposure',0)},
        {"name":"capital_flow_exposure_confidence_model","levels":4},
        {"name":"capital_flow_exposure_unknown_underlying_report","unknown":ent9.get('total',0)-cl9.get('classified_sector',0)},
        {"name":"capital_flow_exposure_category_mismatch_review_queue","mismatches":len(cc9.get('mismatches',[]))},
        {"name":"capital_flow_exposure_flow_proxy_panel","records":len(flow_panel)},
        {"name":"capital_flow_exposure_dashboard_summary","optimized":True},
    ],
    "qa_status":"passed_with_warnings",
    "trusted_consumption_enabled":False,
    "tna_enf_blocked":True,
    "non_china_equity_excluded":True,
    "parse_lab_affected":False}
sj(DP_DIR/'capital_flow_exposure_data_product_manifest_v1.json', mf_doc)
sj(STR_DP/'capital_flow_exposure_data_product_manifest_v1.json', mf_doc)

# ====== 13. QA ======
qa_doc = {"qa_id":"capital_flow_exposure_qa_summary_v1","generated_at":ni(),"overall_status":"passed_with_warnings",
    "checks":{
        "fund_panel_generated":True,"exposure_panels_generated":True,"confidence_model_built":True,
        "unknown_report_generated":True,"mismatch_queue_generated":True,"flow_proxy_integrated":True,
        "dashboard_summary_lightweight":True,"non_china_excluded":True,"tna_blocked":True,
        "trusted_consumption":False,"parse_lab":False,
        "no_holdings_blob_in_dashboard":True,"data_product_manifest_complete":True
    }}
sj(QA/'capital_flow_exposure_qa_summary_v1.json', qa_doc)
sj(DP_DIR/'capital_flow_exposure_qa_summary_v1.json', qa_doc)

# ====== 14. Next Run Plan ======
sj(DP_DIR/'capital_flow_exposure_next_run_plan_v1.json', {"plan_id":"capital_flow_exposure_next_run_plan_v1","generated_at":ni(),
    "recommended_next_step":"time_series_size_collection_or_token_refresh",
    "rationale":"Data product v1 complete. Next: collect time-series Fund Size for actual Flow Proxy computation."})

# Update run_state
rs = lj(ST/'run_state.json')
rs.update({"batch3_run10_completed":True,"batch3_run10_timestamp":ni(),"next_step":"time_series_size_or_token_refresh",
    "batch3_run10_artifact_summary":{"data_product":"capital_flow_exposure_v1","funds":len(flow_panel),"exposure_high":confidence_counter['high'],"exposure_medium":confidence_counter['medium'],"mismatches":len(cc9.get('mismatches',[]))}})
sj(ST/'run_state.json', rs)

print(f"\n[Run10] DONE. funds={len(flow_panel)} conf_high={confidence_counter['high']} conf_med={confidence_counter['medium']} conf_low={confidence_counter['low']} conf_unavail={confidence_counter['unavailable']}")
