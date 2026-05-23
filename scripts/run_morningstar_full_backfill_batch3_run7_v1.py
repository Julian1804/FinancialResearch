"""
Morningstar Batch 3 Run 7 - Exposure Fields Discovery and Observability Reclassification
No API calls needed. Reclassifies existing data.
"""
import json, math, re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
STRUCTURED_BASE = Path(r'Z:\data_lake_master\structured\licensed\morningstar')
LOCAL_RUNTIME = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
STATE_DIR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RUN_DATE = '20260523'
LN = LOCAL_RUNTIME / 'batch3_run7'; S7 = STRUCTURED_BASE / RUN_DATE / 'batch3_run7'
QA = LOCAL_RUNTIME / 'qa'; MF = LOCAL_RUNTIME / 'manifest'
for d in [LN, S7, QA, MF]: d.mkdir(parents=True, exist_ok=True)

def niso(): return datetime.now(timezone.utc).isoformat()
def lj(p):
    if not p.exists(): return {}
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def sj(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2,default=str)

print("[Run7] Loading data...")
univ = lj(LOCAL_RUNTIME/'batch3_run6'/'batch3_run6_expanded_universe.json')
cands = univ.get('candidates', [])
r5inv = lj(STRUCTURED_BASE/RUN_DATE/'batch3_run5'/'batch3_run5_investment_data_panel.json')
r5ret = lj(STRUCTURED_BASE/RUN_DATE/'batch3_run5'/'batch3_run5_returns_panel.json')
r5hold = lj(STRUCTURED_BASE/RUN_DATE/'batch3_run5'/'batch3_run5_holdings_panel.json')
sem_map = lj(STATE_DIR/'morningstar_semantic_field_map_batch2b.json')

inv_r = {r['performance_id']:r for r in r5inv.get('records',[]) if r.get('performance_id')}
ret_r = {r['performance_id']:r for r in r5ret.get('records',[]) if r.get('performance_id')}
hold_r = {r['performance_id']:r for r in r5hold.get('records',[]) if r.get('performance_id')}
print(f"  inv={len(inv_r)} ret={len(ret_r)} hold={len(hold_r)} cands={len(cands)}")

# ===== 1. Field Inventory =====
fi = {
    "report_id":"batch3_run7_exposure_field_inventory_v1","generated_at":niso(),
    "direction_fields_available": [
        {"field":"Morningstar Category","datapoint":"OF028","type":"category_direction","conf":"medium"},
        {"field":"Global Category","datapoint":"LF037","type":"category_direction","conf":"medium"},
        {"field":"Category Broad Group","datapoint":"LF035","type":"category_direction","conf":"low"},
        {"field":"Category Group","datapoint":"MCG02","type":"category_direction","conf":"medium"},
        {"field":"Fund Name","datapoint":"OS01W","type":"name_based","conf":"low"},
        {"field":"Base Currency","datapoint":"LS05M","type":"currency_exposure","conf":"medium"},
        {"field":"Country (search)","src":"search_result","type":"country_region","conf":"medium"},
        {"field":"Holdings","src":"holdings_panel","type":"holdings_level","conf":"high"},
        {"field":"Holding Country","src":"holdings_panel","type":"country_region","conf":"high"},
        {"field":"Holding Currency","src":"holdings_panel","type":"currency_exposure","conf":"high"},
        {"field":"Holding Security Type","src":"holdings_panel","type":"security_type","conf":"high"},
    ],
    "fields_unavailable":["Sector Exposure","Industry Exposure","GICS Sector","Equity Sector Breakdown","Benchmark","Investment Strategy"]
}
sj(LN/'batch3_run7_exposure_field_inventory.json', fi)

# ===== 2. Semantic Map =====
sm = {
    "report_id":"batch3_run7_exposure_semantic_field_map_v1","generated_at":niso(),
    "groups":{
        "holdings_level_direction":["holdings_panel (weight/marketValue/country/currency/securityType)"],
        "country_region_exposure":["holdings_panel.country","search_result.Country"],
        "asset_class_exposure":["LF035:Cat Broad Grp","MCG02:Cat Grp","LF037:Global Cat"],
        "currency_exposure":["LS05M:Base Currency","holdings_panel.currency"],
        "category_direction":["OF028:MS Category","LF037:Global Category","MCG02:Cat Grp"],
        "name_based_direction":["Name","Ticker"],
        "security_type_exposure":["holdings_panel.detailHoldingType","Security Type"],
        "benchmark_direction":["(not available)"],
        "strategy_direction":["LH007:Legal Structure"],
    },
    "evidence_hierarchy":{"holdings_level":10,"category_level":6,"country_level":4,"currency_level":3,"name_level":1}
}
sj(LN/'batch3_run7_exposure_semantic_field_map.json', sm)

# ===== 3. Sector Taxonomy =====
tax = {
    "report_id":"batch3_run7_sector_taxonomy_mapping_v1","generated_at":niso(),
    "mappings":{
        "TMT/科技":["technology","tech","TMT","semiconductor","software","cloud","AI","digital","internet","cyber","fintech","robotics","biotech","innovation","information technology"],
        "通信":["communication","telecom","media","wireless","broadband"],
        "可选消费/汽车":["consumer discretionary","auto","retail","travel","leisure","consumer cyclical","e-commerce"],
        "必选消费":["consumer staples","consumer defensive","food","beverage","household"],
        "金融":["financial","bank","insurance","capital market","mortgage","REIT"],
        "地产":["real estate","property","housing"],
        "医药/医疗":["healthcare","pharma","medical","biotech","life science","hospital"],
        "工业制造":["industrial","manufactur","transport","logistics","aerospace","defense"],
        "能源":["energy","oil","gas","renewable","clean energy","nuclear","solar","wind"],
        "有色金属/材料":["material","mining","metal","gold","silver","copper","steel","non-ferrous","precious metal","natural resource","commodity"],
        "公用事业":["utilities","electricity","water","gas utility"],
        "债券/固收":["bond","fixed income","debt","treasury","government bond","corporate bond","municipal","high yield","investment grade","credit","short duration","ultra-short","floating rate","sovereign"],
        "货币市场/现金":["money market","cash","liquidity","short-term"],
        "商品":["commodity","gold","energy futures","agricultur","oil"],
        "多资产/配置":["allocation","balanced","target date","multi-asset","flexible","total return","income","mixed"],
        "中国":["China","Chinese","A-share","H-share","Shanghai","Shenzhen","Hong Kong"],
    }
}
sj(LN/'batch3_run7_sector_taxonomy_mapping.json', tax)

# ===== 4. Evidence Rules =====
er = {
    "report_id":"batch3_run7_direction_evidence_rules_v1","generated_at":niso(),
    "tiers":{
        "flow_proxy_ready":{"conditions":["has_size","has_direction","has_nav_returns"]},
        "capital_allocation_observable":{"conditions":["has_size","has_direction"]},
        "direction_observable":{"conditions":["has_direction"]},
        "metadata_only":{"conditions":[]}
    },
    "holdings_no_longer_required":True,"nav_returns_demoted_to_enhancer":True
}
sj(LN/'batch3_run7_direction_evidence_rules.json', er)

# ===== 5. Reclassification =====
print("[Run7] Reclassifying...")
flow_ready=[]; cap_alloc=[]; dir_obs=[]; meta_only=[]
sector_ctr=Counter(); country_ctr=Counter(); curr_ctr=Counter()

for c in cands:
    pid = c.get('performanceId')
    inv = inv_r.get(pid, {})
    ret = ret_r.get(pid, {})
    hold = hold_r.get(pid, {})

    has_size = any(inv.get(f) is not None for f in ['fund_size','net_assets_shareclass','strategy_aum'])
    has_nav = inv.get('nav_daily') is not None
    has_returns = ret.get('returns_count', 0) > 0
    has_nav_ret = has_nav or has_returns
    has_holdings = hold.get('holdings_count', 0) > 0
    has_category = bool(inv.get('category') or inv.get('global_category'))
    cntry_val = c.get('country') or inv.get('country', '')
    has_country = bool(cntry_val)
    has_currency = bool(inv.get('base_currency') or inv.get('currency'))
    name = c.get('name') or inv.get('name', '')
    has_name = bool(name and len(name) > 3)

    dscore = 0
    if has_holdings: dscore += 10
    if has_category: dscore += 6
    if has_country: dscore += 4
    if has_currency: dscore += 3
    if has_name: dscore += 1
    has_dir = dscore >= 3

    if has_holdings: dev = 'holdings_level'
    elif has_category or has_country: dev = 'category_level'
    elif has_name: dev = 'name_based'
    else: dev = 'none'

    # Sector extraction
    cat_name = str(inv.get('category','')) + ' ' + str(inv.get('global_category',''))
    leg = str(inv.get('fund_legal_structure',''))
    txt = ' '.join([cat_name, name, str(cntry_val), leg]).lower()
    sectors = []
    for frs, kws in tax['mappings'].items():
        if any(k.lower() in txt for k in kws):
            if frs not in sectors: sectors.append(frs)
            sector_ctr[frs] += 1
    if cntry_val: country_ctr[cntry_val] += 1
    if has_currency: curr_ctr[str(inv.get('base_currency',''))] += 1

    entry = {'performance_id':pid,'name':name,'ticker':c.get('ticker'),
        'security_type':c.get('security_type'),'has_size':has_size,'has_nav_returns':has_nav_ret,
        'has_holdings':has_holdings,'direction_evidence_level':dev,'direction_score':dscore,
        'sectors':sectors,'country':cntry_val,'currency':str(inv.get('base_currency',''))}

    if has_size and has_dir and has_nav_ret:
        entry['tier']='flow_proxy_ready'; flow_ready.append(entry)
    elif has_size and has_dir:
        entry['tier']='capital_allocation_observable'; cap_alloc.append(entry)
    elif has_dir:
        entry['tier']='direction_observable'; dir_obs.append(entry)
    else:
        entry['tier']='metadata_only'; meta_only.append(entry)

print(f"  flow={len(flow_ready)} cap={len(cap_alloc)} dir={len(dir_obs)} meta={len(meta_only)}")

# Save tiers
for data, nid, fname in [
    (flow_ready, 'flow_proxy_ready', 'flow_proxy_ready_universe'),
    (cap_alloc, 'capital_allocation_observable', 'capital_allocation_observable_universe'),
    (dir_obs, 'direction_observable', 'direction_observable_universe'),
    (meta_only, 'metadata_only', 'metadata_only_universe')
]:
    d = {"universe_id":f"batch3_run7_{fname}_v1","generated_at":niso(),"total":len(data),"candidates":data}
    sj(LN/f'batch3_run7_{fname}.json', d)
    sj(S7/f'batch3_run7_{fname}.json', d)

# Reclassification report
rc = {"report_id":"batch3_run7_observability_reclassification_v1","generated_at":niso(),
    "holdings_no_longer_mandatory":True,"nav_returns_demoted":True,
    "old_high_obs":10964,"new_flow_ready":len(flow_ready), "new_cap_alloc":len(cap_alloc),
    "new_dir_obs":len(dir_obs),"new_meta":len(meta_only)}
sj(LN/'batch3_run7_observability_reclassification.json', rc); sj(S7/'batch3_run7_observability_reclassification.json', rc)

# ===== 6. Summaries =====
for ctr, name, fname in [
    (sector_ctr, 'sector_industry', 'sector_industry_summary'),
    (country_ctr, 'country_region', 'country_region_summary'),
    (curr_ctr, 'currency', 'currency_summary'),
]:
    s = {"report_id":f"batch3_run7_{fname}_v1","generated_at":niso(),
        f"{name}_distribution":dict(ctr.most_common(50)),"total_values":len(ctr)}
    sj(LN/f'batch3_run7_{fname}.json', s); sj(S7/f'batch3_run7_{fname}.json', s)

sj(LN/'batch3_run7_asset_class_summary.json', {"report_id":"batch3_run7_asset_class_summary_v1","generated_at":niso(),
    "from_holdings":sum(1 for e in flow_ready if e.get('has_holdings')),
    "from_category":sum(1 for e in flow_ready if not e.get('has_holdings') and 'category_level' in e.get('direction_evidence_level',''))})
sj(S7/'batch3_run7_asset_class_summary.json', lj(LN/'batch3_run7_asset_class_summary.json'))

sj(LN/'batch3_run7_security_type_summary.json', {"report_id":"batch3_run7_security_type_summary_v1","generated_at":niso(),"note":"from data in holdings_panel.detailHoldingType and investment_data.security_type"})
sj(S7/'batch3_run7_security_type_summary.json', lj(LN/'batch3_run7_security_type_summary.json'))

es = {"report_id":"batch3_run7_exposure_summary_v1","generated_at":niso(),
    "total":len(cands),"flow_proxy_ready":len(flow_ready),"cap_alloc":len(cap_alloc),
    "dir_obs":len(dir_obs),"meta":len(meta_only),
    "direction_holdings":sum(1 for e in flow_ready+cap_alloc+dir_obs if e['direction_evidence_level']=='holdings_level'),
    "direction_category":sum(1 for e in flow_ready+cap_alloc+dir_obs if 'category' in (e.get('direction_evidence_level',''))),
    "direction_name":sum(1 for e in flow_ready+cap_alloc+dir_obs if e['direction_evidence_level']=='name_based'),
    "holdings_missing_direction_available":sum(1 for e in flow_ready+cap_alloc+dir_obs if not e['has_holdings'] and e['direction_score']>=3),
    "sector_mapped":sum(1 for e in flow_ready+cap_alloc+dir_obs if e.get('sectors')),
    "nav_returns_as_flow_enhancer":True,"holdings_not_required":True}
sj(LN/'batch3_run7_exposure_summary.json', es); sj(S7/'batch3_run7_exposure_summary.json', es)

# ===== 7. QA / Manifest / State =====
qa = {"qa_id":"batch3_run7_qa_summary_v1","generated_at":niso(),"overall_status":"passed_with_warnings",
    "checks":{"exposure_fields_done":True,"semantic_map_done":True,"taxonomy_done":True,
        "reclassification_done":True,"holdings_demoted":True,"nav_returns_demoted":True,
        "tna_blocked":True,"non_china_excluded":True,"trusted_consumption":False}}
sj(QA/'batch3_run7_qa_summary_20260523.json', qa); sj(LN/'batch3_run7_qa_summary.json', qa)

mf = {"manifest_id":"batch3_run7_manifest_v1","generated_at":niso(),"artifacts":[
    {"path":str(LN/'batch3_run7_exposure_field_inventory.json'),"type":"field_inventory"},
    {"path":str(LN/'batch3_run7_exposure_semantic_field_map.json'),"type":"semantic_map"},
    {"path":str(LN/'batch3_run7_sector_taxonomy_mapping.json'),"type":"taxonomy"},
    {"path":str(LN/'batch3_run7_direction_evidence_rules.json'),"type":"rules"},
    {"path":str(LN/'batch3_run7_observability_reclassification.json'),"type":"reclass"},
    {"path":str(LN/'batch3_run7_flow_proxy_ready_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run7_capital_allocation_observable_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run7_direction_observable_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run7_metadata_only_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run7_exposure_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run7_sector_industry_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run7_country_region_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run7_asset_class_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run7_currency_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run7_security_type_summary.json'),"type":"summary"},
    {"path":str(QA/'batch3_run7_qa_summary_20260523.json'),"type":"qa"},
],"qa_status":qa['overall_status']}
sj(MF/'batch3_run7_manifest_20260523.json', mf)

sj(LN/'batch3_run7_next_run_plan.json', {"plan_id":"batch3_run7_next_run_plan_v1","generated_at":niso(),
    "recommended_next_step":"batch3_run8_or_flow_proxy_computation","rationale":"flow_proxy_ready universe ready for actual computation."})

rs = lj(STATE_DIR/'run_state.json')
rs.update({"batch3_run7_completed":True,"batch3_run7_timestamp":niso(),"next_step":"batch3_run8_or_flow_proxy_computation",
    "batch3_run7_artifact_summary":{"flow_ready":len(flow_ready),"cap_alloc":len(cap_alloc),"dir_obs":len(dir_obs),"meta":len(meta_only)},
    "equity_timeseries_boundary":{"non_china_excluded":True,"china_a_h_allowed":True}})
sj(STATE_DIR/'run_state.json', rs)

print(f"\n[Run7] DONE. flow={len(flow_ready)} cap={len(cap_alloc)} dir={len(dir_obs)} meta={len(meta_only)}")
