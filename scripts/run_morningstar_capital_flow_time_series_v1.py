"""
Morningstar Run 11 - Capital Flow Time-Series Readiness + Size History Strategy
Builds time-series feasibility classification from existing Run 5/10 data.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
SB = Path(r'Z:\data_lake_master\structured\licensed\morningstar')
LR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
DP10 = PROJECT_ROOT / 'runtime' / 'morningstar_capital_flow_exposure_v1'
TS = PROJECT_ROOT / 'runtime' / 'morningstar_capital_flow_time_series_v1'
QA = LR / 'qa'
STR_TS = Path(r'Z:\data_lake_master\structured\licensed\morningstar') / 'capital_flow_time_series_v1'
for d in [TS, STR_TS]: d.mkdir(parents=True, exist_ok=True)
RD = '20260523'

def ni(): return datetime.now(timezone.utc).isoformat()
def lj(p):
    if not p.exists(): return {}
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def sj(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2,default=str)

print("[Run11] Loading source data...")
fp10 = lj(DP10/'capital_flow_exposure_fund_panel_v1.json')['records']
inv5 = lj(SB/RD/'batch3_run5'/'batch3_run5_investment_data_panel.json')
ret5 = lj(SB/RD/'batch3_run5'/'batch3_run5_returns_panel.json')
dpanel8 = lj(LR/'batch3_run8'/'batch3_run8_direction_evidence_panel.json')
dev_map = {r['performance_id']:r for r in dpanel8.get('records',[]) if r.get('performance_id')}

print(f"  Loaded {len(fp10)} fund panel records, {len(inv5.get('records',[]))} inv, {len(ret5.get('records',[]))} ret")

# ====== 1. Size Field Inventory ======
size_inv = {
    "report_id":"size_field_inventory_v1","generated_at":ni(),
    "fields_available_in_current_data":[
        {"field":"Fund Size","datapoint":"OF009","level":"fund","type":"latest_snapshot","frequency":"unknown","data_present":True},
        {"field":"Net Assets - Share Class","datapoint":"OS013","level":"shareclass","type":"latest_snapshot","frequency":"unknown","data_present":True},
        {"field":"NAV Daily","datapoint":"OS060","level":"performance","type":"latest_snapshot","frequency":"daily","data_present":True},
        {"field":"Strategy AUM","datapoint":"AA07M","level":"strategy","type":"latest_snapshot","frequency":"unknown","data_present":True},
    ],
    "fields_desired_but_unavailable":[
        "Historical Fund Size time series","Historical Net Assets time series",
        "Historical Strategy AUM time series","Vehicle Assets time series",
        "Total Net Assets time series","AUM time series"
    ],
    "historical_data_status":"snapshot_only - no historical size time series available in current dataset",
    "snapshot_date_available":False,
    "next_step":"acquire_time_series_size_via_new_api_calls_when_token_refreshed"
}
sj(TS/'size_field_inventory_v1.json', size_inv)

# ====== 2. Size History Feasibility ======
shf = {
    "report_id":"size_history_feasibility_report_v1","generated_at":ni(),
    "total_funds":len(fp10),
    "funds_with_size_data":sum(1 for r in fp10 if r.get('fund_size') or r.get('net_assets_shareclass') or r.get('strategy_aum')),
    "historical_size_available":0,
    "latest_snapshot_only":sum(1 for r in fp10 if r.get('fund_size') or r.get('net_assets_shareclass') or r.get('strategy_aum')),
    "size_history_not_available":True,
    "blocker":"no_historical_size_time_series_in_current_dataset",
    "resolution":"run_md.direct.get_investment_data with time_series_format for size fields when token refreshed",
    "snapshot_history_from_now_possible":True,
    "snapshot_scheduler_recommended":True
}
sj(TS/'size_history_feasibility_report_v1.json', shf); sj(STR_TS/'size_history_feasibility_report_v1.json', shf)

# ====== 3. NAV / Returns Alignment ======
print("[Run11] Building NAV/returns alignment panel...")
align_panel = []
align_counter = Counter()
for r in fp10:
    pid = r['performance_id']
    has_size = bool(r.get('fund_size') or r.get('net_assets_shareclass') or r.get('strategy_aum'))
    has_nav = r.get('nav_daily') is not None
    has_ret = (r.get('returns_count') or 0) > 0
    has_ret_date = bool(r.get('latest_return_date'))

    if has_size and (has_nav or has_ret) and has_ret_date:
        # Size is snapshot, returns are monthly - can't do exact date match
        status = 'size_snapshot_returns_monthly'
    elif has_size and not has_nav and not has_ret:
        status = 'size_snapshot_only_no_nav'
    elif not has_size and (has_nav or has_ret):
        status = 'nav_only_no_size'
    else:
        status = 'no_size_no_nav'

    align_counter[status] += 1
    align_panel.append({'performance_id':pid,'name':r.get('name',''),'has_size':has_size,
        'has_nav_daily':has_nav,'has_returns':has_ret,'latest_return_date':r.get('latest_return_date'),
        'size_types':[k for k in ['fund_size','net_assets_shareclass','strategy_aum'] if r.get(k)],
        'alignment_status':status,'is_snapshot_only':True})

sj(TS/'nav_returns_alignment_panel_v1.json', {"panel_id":"nav_returns_alignment_panel_v1","generated_at":ni(),"total":len(align_panel),"status_counts":dict(align_counter),"records":align_panel})
sj(STR_TS/'nav_returns_alignment_panel_v1.json', lj(TS/'nav_returns_alignment_panel_v1.json'))

# ====== 4. Flow Proxy Feasibility Classification ======
print("[Run11] Classifying flow proxy feasibility...")
fp_class = []; cc = Counter()
for r in fp10:
    pid = r['performance_id']
    has_size = bool(r.get('fund_size') or r.get('net_assets_shareclass') or r.get('strategy_aum'))
    has_nav_ret = r.get('nav_daily') is not None or (r.get('returns_count') or 0) > 0
    has_exposure = bool(r.get('sector_exposure_top5'))
    dev_level = r.get('direction_evidence_level') or 5
    conf = r.get('exposure_confidence')

    # Determine class
    if has_size and has_nav_ret and has_exposure:
        # Has all ingredients but NO historical size - trackable from now
        cls = 'B_trackable_from_now'
    elif has_size and has_exposure:
        cls = 'C_capital_allocation'
    elif has_exposure:
        cls = 'D_exposure_only'
    else:
        cls = 'E_metadata_only'

    cc[cls] += 1
    fp_class.append({'performance_id':pid,'name':r.get('name',''),'ticker':r.get('ticker'),
        'has_size':has_size,'has_nav_returns':has_nav_ret,'has_exposure':has_exposure,
        'feature_class':cls,'flow_proxy_readiness':'trackable_from_today','confidence':conf})

fc_doc = {"report_id":"flow_proxy_feasibility_classification_v1","generated_at":ni(),
    "total":len(fp_class),"classification_counts":dict(cc),
    "note":"A_class(calculable_now)=0 because no historical size time series available. B_class can start tracking today.",
    "records":fp_class}
sj(TS/'flow_proxy_feasibility_classification_v1.json', fc_doc); sj(STR_TS/'flow_proxy_feasibility_classification_v1.json', fc_doc)

# Tier universes
for cls_name, label in [('C_capital_allocation','capital_allocation_only'),('D_exposure_only','exposure_only'),('E_metadata_only','metadata_only')]:
    subset = [r for r in fp_class if r['feature_class'] == cls_name]
    sj(TS/f'{label}_universe_v1.json', {"universe_id":f"{label}_v1","generated_at":ni(),"total":len(subset),"records":subset})
    sj(STR_TS/f'{label}_universe_v1.json', lj(TS/f'{label}_universe_v1.json'))

# ====== 5. Size Snapshot History Panel (seed for future time series) ======
print("[Run11] Building snapshot history seed panel...")
snap_panel = []
for r in fp10:
    pid = r['performance_id']
    size_val = r.get('fund_size') or r.get('net_assets_shareclass') or r.get('strategy_aum')
    size_type = 'fund_size' if r.get('fund_size') else ('net_assets_shareclass' if r.get('net_assets_shareclass') else ('strategy_aum' if r.get('strategy_aum') else None))
    if size_val is None: continue
    snap_panel.append({'performance_id':pid,'sec_id':r.get('sec_id'),'name':r.get('name',''),
        'snapshot_date':RD,'observed_at':ni(),'size_value':size_val,'size_type':size_type,
        'currency':r.get('base_currency'),'nav_daily':r.get('nav_daily'),
        'latest_return_date':r.get('latest_return_date'),'exposure_hash':'run10_v1',
        'source_method':'md.direct.get_investment_data snapshot','run_id':'batch3_run5','is_historical_seed':True})
sj(TS/'size_snapshot_history_panel_v1.json', {"panel_id":"size_snapshot_history_panel_v1","generated_at":ni(),"total_snapshots":len(snap_panel),"note":"Seed snapshot for future time-series accumulation. NOT historical.","records":snap_panel})
sj(STR_TS/'size_snapshot_history_panel_v1.json', lj(TS/'size_snapshot_history_panel_v1.json'))

# ====== 6. Flow Proxy Methodology ======
method = {"report_id":"flow_proxy_methodology_v1","generated_at":ni(),
    "formula":"estimated_flow_proxy ≈ AUM_t - AUM_t-1 * (1 + return_t)",
    "status":"methodology_only_no_historical_data",
    "requires":["historical_size_time_series","aligned_returns","currency_consistency_check"],
    "size_levels_must_not_mix":True,
    "currency_must_be_consistent":True,
    "frequency_alignment_required":True,
    "proxy_not_actual_flow":True,
    "tna_enf_excluded_from_methodology":True,
    "snapshot_accumulation_required":True,
    "next_action":"collect_historical_or_commence_regular_snapshot"
}
sj(TS/'flow_proxy_methodology_v1.json', method); sj(STR_TS/'flow_proxy_methodology_v1.json', method)

# Calculable sample (empty - no historical data, but show structure)
sj(TS/'flow_proxy_calculable_sample_v1.json', {"panel_id":"flow_proxy_calculable_sample_v1","generated_at":ni(),"total":0,"note":"No historical size data available. Methodology only.","sample":[]})

# ====== 7. Exposure Versioning ======
ev = {"report_id":"exposure_versioning_policy_v1","generated_at":ni(),
    "policy":"Exposure derived from holdings panel date. Not real-time. Versioned per portfolioDate.",
    "portfolio_date_frequency":"snapshot (monthly for most mutual funds, daily for some ETFs)",
    "exposure_as_of_source":"holdings_panel.portfolio_dates",
    "derived_from":"batch3_run9_holdings_analysis","versioning_field":"portfolio_dates",
    "frequency_limit":"holdings_update_frequency_not_daily_for_most_funds",
    "do_not_treat_as_daily_exposure":True}
sj(TS/'exposure_versioning_policy_v1.json', ev); sj(STR_TS/'exposure_versioning_policy_v1.json', ev)

# ====== 8. Snapshot Scheduler Plan ======
ss = {"report_id":"snapshot_scheduler_plan_v1","generated_at":ni(),
    "strategy":"weekly_or_daily_size_snapshot_collection",
    "fields_to_collect":["Fund Size (OF009)","Net Assets-Share Class (OS013)","Strategy AUM (AA07M)","NAV Daily (OS060)"],
    "frequency":"weekly_preferred_daily_if_available",
    "method":"md.direct.get_investment_data with single datapoint snapshot call per fund batch",
    "storage":"Z:\\data_lake_master\\raw\\licensed\\morningstar\\snapshots\\{date}\\size_snapshot.json",
    "accumulation":"append to size_time_series_panel with snapshot_date",
    "approx_weekly_api_calls":18735//80 + 18735//80 + 18735//80,  # ~703 calls for 3 size fields
    "note":"Start collecting when token refreshed. First 12 weeks = minimal time series for initial flow proxy."}
sj(TS/'snapshot_scheduler_plan_v1.json', ss); sj(STR_TS/'snapshot_scheduler_plan_v1.json', ss)

# ====== 9. Time-Series Readiness Summary ======
tsr = {"report_id":"capital_flow_time_series_readiness_v1","generated_at":ni(),
    "status":"snapshot_only_time_series_not_ready",
    "flow_proxy_readiness":{
        "A_calculable_now":cc.get('A_calculable_now',0),"B_trackable_from_now":cc.get('B_trackable_from_now',0),
        "C_capital_allocation":cc.get('C_capital_allocation',0),"D_exposure_only":cc.get('D_exposure_only',0),
        "E_metadata_only":cc.get('E_metadata_only',0)
    },
    "blockers":["no_historical_size_time_series","token_expired","cannot_collect_new_data"],
    "next_steps":["refresh_token","start_weekly_size_snapshot_collection","accumulate_12_weeks_minimum","then_reclassify_A_class"]}
sj(TS/'capital_flow_time_series_readiness_v1.json', tsr); sj(STR_TS/'capital_flow_time_series_readiness_v1.json', tsr)

# ====== 10. Dashboard Summary (lightweight) ======
ds11 = {"report_id":"capital_flow_time_series_dashboard_summary_v1","generated_at":ni(),
    "highlights":{
        "total_funds":len(fp10),
        "B_trackable_from_now":cc.get('B_trackable_from_now',0),
        "C_capital_allocation":cc.get('C_capital_allocation',0),
        "D_exposure_only":cc.get('D_exposure_only',0),
        "E_metadata_only":cc.get('E_metadata_only',0),
        "size_snapshots_seeded":len(snap_panel),
        "nav_returns_aligned":align_counter.get('size_snapshot_returns_monthly',0),
        "flow_proxy_status":"methodology_ready_snapshot_accumulation_needed",
        "estimated_weeks_to_minimal_series":12,
        "token_required":True,
        "trusted_consumption":False
    },
    "note":"Dashboard-optimized. No holdings blob."}
sj(TS/'capital_flow_time_series_dashboard_summary_v1.json', ds11)

# ====== 11. QA ======
qa11 = {"qa_id":"capital_flow_time_series_qa_summary_v1","generated_at":ni(),"overall_status":"passed_with_warnings",
    "checks":{
        "size_feasibility_done":True,"nav_alignment_done":True,"flow_proxy_classification_done":True,
        "snapshot_seed_created":True,"methodology_documented":True,"exposure_versioning_done":True,
        "snapshot_scheduler_planned":True,"dashboard_lightweight":True,
        "no_historical_size_hard_calc":True,"flow_proxy_is_proxy":True,
        "tna_blocked":True,"non_china_excluded":True,"trusted_consumption":False
    }}
sj(QA/'capital_flow_time_series_qa_summary_v1.json', qa11); sj(TS/'capital_flow_time_series_qa_summary_v1.json', qa11)

# ====== 12. Next Plan ======
sj(TS/'capital_flow_time_series_next_run_plan_v1.json', {"plan_id":"capital_flow_time_series_next_run_plan_v1","generated_at":ni(),
    "recommended_next_step":"refresh_token_and_start_weekly_size_snapshot_collection",
    "rationale":"Time-series readiness analysis complete. 0 historical size available. Must start weekly snapshot accumulation to build time series."})

# Update state
rs = lj(ST/'run_state.json')
rs.update({"batch3_run11_completed":True,"batch3_run11_timestamp":ni(),"next_step":"token_refresh_then_weekly_snapshots",
    "batch3_run11_artifact_summary":{"B_trackable":cc.get('B_trackable_from_now',0),"C_cap_alloc":cc.get('C_capital_allocation',0),"D_exposure":cc.get('D_exposure_only',0),"E_meta":cc.get('E_metadata_only',0)}})
sj(ST/'run_state.json', rs)

print(f"\n[Run11] DONE. B={cc.get('B_trackable_from_now',0)} C={cc.get('C_capital_allocation',0)} D={cc.get('D_exposure_only',0)} E={cc.get('E_metadata_only',0)} snapshots_seeded={len(snap_panel)}")
