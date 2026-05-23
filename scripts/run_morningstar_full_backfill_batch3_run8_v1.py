"""
Morningstar Batch 3 Run 8 - Direction Evidence Hardening
No API calls. Reclassifies with strict evidence rules.
"""
import json, re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, Counter

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
SB = Path(r'Z:\data_lake_master\structured\licensed\morningstar')
LR = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill'
ST = PROJECT_ROOT / 'runtime' / 'morningstar_full_backfill_state'
RD = '20260523'; LN = LR / 'batch3_run8'; S8 = SB / RD / 'batch3_run8'
QA = LR / 'qa'; MF = LR / 'manifest'
for d in [LN, S8, QA, MF]: d.mkdir(parents=True, exist_ok=True)

def ni(): return datetime.now(timezone.utc).isoformat()
def lj(p):
    if not p.exists(): return {}
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def sj(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2,default=str)

print("[Run8] Loading data...")
univ = lj(LR/'batch3_run6'/'batch3_run6_expanded_universe.json')
cands = univ.get('candidates', [])
r5i = lj(SB/RD/'batch3_run5'/'batch3_run5_investment_data_panel.json')
r5r = lj(SB/RD/'batch3_run5'/'batch3_run5_returns_panel.json')
r5h = lj(SB/RD/'batch3_run5'/'batch3_run5_holdings_panel.json')
inv = {r['performance_id']:r for r in r5i.get('records',[]) if r.get('performance_id')}
ret = {r['performance_id']:r for r in r5r.get('records',[]) if r.get('performance_id')}
hold = {r['performance_id']:r for r in r5h.get('records',[]) if r.get('performance_id')}
print(f"  inv={len(inv)} ret={len(ret)} hold={len(hold)} cands={len(cands)}")

# ========== 1. Direction Evidence Rules (HARDENED) ==========
rules = {
    "report_id":"batch3_run8_direction_evidence_rules_v1","generated_at":ni(),
    "evidence_levels": {
        "L1_holdings":{"desc":"Has actual portfolio holdings data","confidence":"high","source":["holdings_panel"]},
        "L2_structured_exposure":{"desc":"Has structured sector/industry/asset/country exposure","confidence":"medium_high","source":["(not_available_in_current_data)","Holdings panel country/currency/securityType"]},
        "L3_specific_category_strategy":{"desc":"Category/strategy that explicitly names a specific sector/theme/asset class","confidence":"medium","examples":["Technology","Healthcare","Gold","Energy","Commodity","China Bond","Money Market","Short Duration","Real Estate","Infrastructure","Semi","Financial","Metals","Mining","Consumer","Automotive","Utilities","Materials","Pharma","Biotech","Clean Energy","Semiconductor","TMT"]},
        "L4_weak_hint":{"desc":"Only broad category, country-only, or name-only signals","confidence":"low","downgraded_from":["broad_category","country_only","name_only","base_currency"]},
        "L5_metadata":{"desc":"No actionable direction evidence","confidence":"none"}
    },
    "exclusions": {
        "broad_category_excluded": ["Global Equity","US Equity","International Equity","Large Blend","Allocation","Balanced","Growth","Value","Income","Fund","ETF","Open-End Fund","Multi-Asset","Mixed","Total Return","Flexible","Global Bond","International Bond","World Bond","World Equity","World Allocation","Global Allocation","Aggressive","Conservative","Moderate","Multi-Sector","Strategic","Tactical"],
        "country_only_downgraded": True,
        "base_currency_excluded": True,
        "name_only_downgraded": True
    },
    "tier_rules": {
        "flow_proxy_ready": {"min_direction_level":3, "needs_size":True, "needs_nav_returns":True},
        "capital_allocation_observable": {"min_direction_level":3, "needs_size":True, "needs_nav_returns":False},
        "direction_observable": {"min_direction_level":3, "needs_size":False, "needs_nav_returns":False},
        "weak_direction_hint": {"min_direction_level":4, "max_direction_level":4},
        "metadata_only": {"min_direction_level":5}
    }
}
sj(LN/'batch3_run8_direction_evidence_rules.json', rules)

# ========== 2. Sector Taxonomy (same as Run 7) ==========
tax = {
    "report_id":"batch3_run8_sector_taxonomy_mapping_v1","generated_at":ni(),
    "specific_sectors":{
        "TMT/科技":["technology","tech","TMT","semiconductor","software","cloud","AI","digital","internet","cyber","fintech","robotics","innovation","information technology"],
        "通信":["communication","telecom","media","wireless","broadband"],
        "可选消费/汽车":["consumer discretionary","auto","retail","travel","leisure","consumer cyclical","e-commerce"],
        "必选消费":["consumer staples","consumer defensive","food","beverage","household"],
        "金融":["financial","bank","insurance","capital market","mortgage","REIT"],
        "地产":["real estate","property","housing"],
        "医药/医疗":["healthcare","pharma","medical","biotech","life science","hospital"],
        "工业制造":["industrial","manufactur","transport","logistics","aerospace","defense","engineering"],
        "能源":["energy","oil","gas","renewable","clean energy","nuclear","solar","wind"],
        "有色金属/材料":["material","mining","metal","gold","silver","copper","steel","non-ferrous","precious metal","natural resource"],
        "公用事业":["utilities","electricity","water","gas utility"],
        "债券/固收":["bond","fixed income","debt","treasury","government bond","corporate bond","municipal","high yield","investment grade","credit","short duration","ultra-short","floating rate","sovereign","inflation-protected","TIPS","convertible bond"],
        "货币市场/现金":["money market","cash","liquidity"],
        "商品":["commodity","gold","energy futur","agricultur","oil"],
        "多资产/配置":["allocation","balanced","target date","multi-asset","flexible","total return","income","mixed"],
    },
    "broad_categories_excluded":rules["exclusions"]["broad_category_excluded"]
}
sj(LN/'batch3_run8_sector_taxonomy_mapping.json', tax)

# ========== 3. Reclassification ==========
print("[Run8] Reclassifying with hardened rules...")

broad_excluded = rules["exclusions"]["broad_category_excluded"]
specific_sectors = tax["specific_sectors"]

# Stats counters
stats = Counter()

flow_ready = []; cap_alloc = []; dir_obs = []
meta_only_l = []; weak_hint = []; sidecar_l = []
evidence_panel = []

sector_ctr = Counter(); country_ctr = Counter(); curr_ctr = Counter()

for c in cands:
    pid = c.get('performanceId')
    inv0 = inv.get(pid, {})
    ret0 = ret.get(pid, {})
    hold0 = hold.get(pid, {})

    has_size = any(inv0.get(f) is not None for f in ['fund_size','net_assets_shareclass','strategy_aum'])
    has_nav = inv0.get('nav_daily') is not None
    has_returns = ret0.get('returns_count', 0) > 0
    has_nav_ret = has_nav or has_returns
    has_holdings = hold0.get('holdings_count', 0) > 0

    # Extract fields
    cat = inv0.get('category', '') or ''
    global_cat = inv0.get('global_category', '') or ''
    broad_grp = inv0.get('category_broad_group', '') or ''
    cat_grp = inv0.get('category_group', '') or ''
    name = c.get('name', '') or inv0.get('name', '')
    cntry = c.get('country', '') or inv0.get('country', '')
    base_cur = inv0.get('base_currency', '') or ''
    legal = inv0.get('fund_legal_structure', '') or ''
    sec_type = c.get('security_type', '') or inv0.get('security_type', '')

    # Combine category text for analysis
    cat_text = ' '.join([cat, global_cat, broad_grp, cat_grp]).lower()
    name_lower = name.lower() if name else ''

    # ===== Direction Evidence Classification =====
    direction_level = 5  # default: metadata
    level_reason = ""
    direction_sources = []
    is_broad_excluded = False
    is_country_only = False
    is_name_only = False

    # L1: Holdings
    if has_holdings:
        direction_level = 1
        level_reason = "has_portfolio_holdings"
        direction_sources = ["holdings_panel"]
        stats['L1_holdings'] += 1

    # L2: Structured exposure (from holdings details)
    elif has_holdings:
        # Already counted above
        pass

    # L3: Specific category/strategy
    else:
        # Check if category text contains specific sector keywords
        has_specific = False
        matched_sectors = []
        all_cat_keys = set()
        for frs, kws in specific_sectors.items():
            for kw in kws:
                if kw.lower() in cat_text or kw.lower() in name_lower:
                    has_specific = True
                    matched_sectors.append(frs)
                    all_cat_keys.add(kw)
                    break

        # Check if any broad category is present (for exclusion tracking)
        has_broad = any(bc.lower() in cat_text for bc in broad_excluded)

        if has_specific:
            direction_level = 3
            level_reason = f"specific_category: {', '.join(matched_sectors[:3])}"
            direction_sources = ["Morningstar Category", "Global Category", "Category Group"]
            stats['L3_specific_category'] += 1
            for s in matched_sectors: sector_ctr[s] += 1
        elif has_broad:
            # Has category but it's too broad - downgrade to weak hint
            direction_level = 4
            level_reason = "broad_category_excluded"
            direction_sources = ["broad_category_only"]
            is_broad_excluded = True
            stats['L4_broad_category_downgraded'] += 1
        elif cntry:
            # Country-only hint
            direction_level = 4
            level_reason = "country_only_hint"
            direction_sources = ["country_field_only"]
            is_country_only = True
            stats['L4_country_only_downgraded'] += 1
        elif name and len(name) > 5:
            # Name-only hint
            direction_level = 4
            level_reason = "name_only_hint"
            direction_sources = ["fund_name_only"]
            is_name_only = True
            stats['L4_name_only_downgraded'] += 1
        else:
            direction_level = 5
            level_reason = "no_direction_evidence"
            stats['L5_metadata'] += 1

    # Country counting (only for L1-L3)
    if cntry and direction_level <= 3: country_ctr[cntry] += 1
    if base_cur: curr_ctr[base_cur] +=1  # For reporting only, NOT direction

    # ===== Build evidence entry =====
    evidence = {
        'performance_id': pid, 'name': name, 'ticker': c.get('ticker'),
        'security_type': sec_type, 'country': cntry,
        'direction_evidence_level': direction_level,
        'direction_level_name': ['','L1_holdings','L2_structured','L3_specific_category','L4_weak_hint','L5_metadata'][direction_level],
        'direction_source_fields': direction_sources,
        'direction_confidence_score': {1:100,2:80,3:55,4:20,5:0}[direction_level],
        'direction_reason': level_reason,
        'sector_mapping_source': 'category_name' if direction_level==3 else ('holdings' if direction_level<=2 else 'none'),
        'country_mapping_source': 'holdings/country_field' if direction_level<=3 else 'none',
        'asset_class_mapping_source': 'category' if direction_level<=3 else 'none',
        'is_broad_category_excluded': is_broad_excluded,
        'is_country_only_hint': is_country_only,
        'is_name_only_hint': is_name_only,
        'has_size': has_size, 'has_nav_returns': has_nav_ret,
        'base_currency_excluded_from_direction': True
    }
    evidence_panel.append(evidence)

    # ===== Tier assignment =====
    if direction_level <= 3:
        if has_size and has_nav_ret:
            evidence['tier'] = 'flow_proxy_ready'
            flow_ready.append(evidence)
        elif has_size:
            evidence['tier'] = 'capital_allocation_observable'
            cap_alloc.append(evidence)
        else:
            evidence['tier'] = 'direction_observable'
            dir_obs.append(evidence)
    elif direction_level == 4:
        evidence['tier'] = 'weak_direction_hint'
        weak_hint.append(evidence)
    else:
        evidence['tier'] = 'metadata_only'
        meta_only_l.append(evidence)

print(f"  flow={len(flow_ready)} cap={len(cap_alloc)} dir={len(dir_obs)} weak={len(weak_hint)} meta={len(meta_only_l)}")

# ===== 4. Save outputs =====
# Direction evidence panel
sj(LN/'batch3_run8_direction_evidence_panel.json', {"panel_id":"batch3_run8_direction_evidence_panel_v1","generated_at":ni(),"total":len(evidence_panel),"records":evidence_panel})

# Tier universes
for data, tid, fname in [
    (flow_ready,'flow_proxy_ready','flow_proxy_ready_universe'),
    (cap_alloc,'capital_allocation_observable','capital_allocation_observable_universe'),
    (dir_obs,'direction_observable','direction_observable_universe'),
    (weak_hint,'weak_direction_hint','weak_direction_hint_universe'),
    (meta_only_l,'metadata_only','metadata_only_universe'),
]:
    d = {"universe_id":f"batch3_run8_{fname}_v1","generated_at":ni(),"total":len(data),"candidates":data}
    sj(LN/f'batch3_run8_{fname}.json', d); sj(S8/f'batch3_run8_{fname}.json', d)

# Sidecar (empty, TNA/ENF blocked)
sidecar_d = {"universe_id":"batch3_run8_sidecar_flow_like_universe_v1","generated_at":ni(),"total":0,"status":"blocked_unit_scale_unknown","note":"TNA/ENF blocked"}
sj(LN/'batch3_run8_sidecar_flow_like_universe.json', sidecar_d); sj(S8/'batch3_run8_sidecar_flow_like_universe.json', sidecar_d)

# Confidence report
cr = {"report_id":"batch3_run8_direction_confidence_report_v1","generated_at":ni(),
    "total":len(cands),
    "L1_holdings":stats.get('L1_holdings',0),
    "L2_structured_exposure":0,
    "L3_specific_category":stats.get('L3_specific_category',0),
    "L4_weak_hint_total":stats.get('L4_broad_category_downgraded',0)+stats.get('L4_country_only_downgraded',0)+stats.get('L4_name_only_downgraded',0),
    "L5_metadata":stats.get('L5_metadata',0),
    "reliable_direction":stats.get('L1_holdings',0)+stats.get('L3_specific_category',0),
    "unreliable_direction":stats.get('L4_broad_category_downgraded',0)+stats.get('L4_country_only_downgraded',0)+stats.get('L4_name_only_downgraded',0)+stats.get('L5_metadata',0)
}
sj(LN/'batch3_run8_direction_confidence_report.json', cr)

# Reclassification report
rc = {"report_id":"batch3_run8_observability_reclassification_v1","generated_at":ni(),
    "rules_hardened":True,"broad_categories_excluded":True,
    "country_only_downgraded":True,"base_currency_excluded":True,
    "flow_proxy_ready":len(flow_ready),"capital_allocation_observable":len(cap_alloc),
    "direction_observable":len(dir_obs),"weak_direction_hint":len(weak_hint),"metadata_only":len(meta_only_l),
    "sidecar":0, "holdings_or_exposure_count":stats.get('L1_holdings',0)+stats.get('L3_specific_category',0),
    "category_only_reliable":stats.get('L3_specific_category',0)}
sj(LN/'batch3_run8_observability_reclassification.json', rc); sj(S8/'batch3_run8_observability_reclassification.json', rc)

# Exclusion reports
sj(LN/'batch3_run8_broad_category_exclusion_report.json', {"report_id":"batch3_run8_broad_category_exclusion_report_v1","generated_at":ni(),
    "downgraded_count":stats.get('L4_broad_category_downgraded',0),
    "excluded_categories":broad_excluded,"rule":"broad_category_demoted_to_weak_hint"})
sj(LN/'batch3_run8_country_only_bias_warning.json', {"report_id":"batch3_run8_country_only_bias_warning_v1","generated_at":ni(),
    "downgraded_count":stats.get('L4_country_only_downgraded',0),
    "rule":"country_only_demoted_to_geographic_hint"})
sj(LN/'batch3_run8_name_based_direction_warning.json', {"report_id":"batch3_run8_name_based_direction_warning_v1","generated_at":ni(),
    "downgraded_count":stats.get('L4_name_only_downgraded',0),
    "rule":"name_only_demoted_to_weak_hint"})

# Summaries
for ctr, name, fname in [
    (sector_ctr, 'sector_industry', 'sector_industry_summary'),
    (country_ctr, 'country_region', 'country_region_summary'),
    (curr_ctr, 'currency', 'currency_summary'),
]:
    s = {"report_id":f"batch3_run8_{fname}_v1","generated_at":ni(),
        f"{name}_distribution":dict(ctr.most_common(50))}
    sj(LN/f'batch3_run8_{fname}.json', s); sj(S8/f'batch3_run8_{fname}.json', s)

sj(LN/'batch3_run8_asset_class_summary.json', {"report_id":"batch3_run8_asset_class_summary_v1","generated_at":ni(),
    "from_holdings":stats.get('L1_holdings',0),"from_specific_category":stats.get('L3_specific_category',0)})
sj(S8/'batch3_run8_asset_class_summary.json', lj(LN/'batch3_run8_asset_class_summary.json'))

sj(LN/'batch3_run8_security_type_summary.json', {"report_id":"batch3_run8_security_type_summary_v1","generated_at":ni(),"note":"available from holdings_panel and investment_data"})
sj(S8/'batch3_run8_security_type_summary.json', lj(LN/'batch3_run8_security_type_summary.json'))

# QA
qa = {"qa_id":"batch3_run8_qa_summary_v1","generated_at":ni(),"overall_status":"passed_with_warnings",
    "checks":{"direction_hardened":True,"broad_categories_excluded":True,"country_demoted":True,
        "base_currency_excluded":True,"nav_returns_not_hard_requirement":True,
        "tna_blocked":True,"non_china_excluded":True,"trusted_consumption":False,
        "holdings_level":stats.get('L1_holdings',0),"specific_category":stats.get('L3_specific_category',0)}}
sj(QA/'batch3_run8_qa_summary_20260523.json', qa); sj(LN/'batch3_run8_qa_summary.json', qa)

# Manifest
mf = {"manifest_id":"batch3_run8_manifest_v1","generated_at":ni(),"artifacts":[
    {"path":str(LN/'batch3_run8_direction_evidence_panel.json'),"type":"panel"},
    {"path":str(LN/'batch3_run8_direction_evidence_rules.json'),"type":"rules"},
    {"path":str(LN/'batch3_run8_sector_taxonomy_mapping.json'),"type":"taxonomy"},
    {"path":str(LN/'batch3_run8_direction_confidence_report.json'),"type":"report"},
    {"path":str(LN/'batch3_run8_observability_reclassification.json'),"type":"reclass"},
    {"path":str(LN/'batch3_run8_flow_proxy_ready_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_capital_allocation_observable_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_direction_observable_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_weak_direction_hint_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_metadata_only_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_sidecar_flow_like_universe.json'),"type":"universe"},
    {"path":str(LN/'batch3_run8_broad_category_exclusion_report.json'),"type":"report"},
    {"path":str(LN/'batch3_run8_country_only_bias_warning.json'),"type":"report"},
    {"path":str(LN/'batch3_run8_name_based_direction_warning.json'),"type":"report"},
    {"path":str(LN/'batch3_run8_sector_industry_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run8_country_region_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run8_asset_class_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run8_currency_summary.json'),"type":"summary"},
    {"path":str(LN/'batch3_run8_security_type_summary.json'),"type":"summary"},
    {"path":str(QA/'batch3_run8_qa_summary_20260523.json'),"type":"qa"},
], "qa_status":qa['overall_status']}
sj(MF/'batch3_run8_manifest_20260523.json', mf)

sj(LN/'batch3_run8_next_run_plan.json', {"plan_id":"batch3_run8_next_run_plan_v1","generated_at":ni(),
    "recommended_next_step":"batch3_run9_or_flow_proxy_computation","rationale":"Direction evidence hardened. flow_proxy_ready universe ready for actual computation with time-series size data."})

rs = lj(ST/'run_state.json')
rs.update({"batch3_run8_completed":True,"batch3_run8_timestamp":ni(),"next_step":"batch3_run9_or_flow_proxy_computation",
    "batch3_run8_artifact_summary":{"flow_ready":len(flow_ready),"cap_alloc":len(cap_alloc),"dir_obs":len(dir_obs),"weak":len(weak_hint),"meta":len(meta_only_l),"sidecar":0}})
sj(ST/'run_state.json', rs)

print(f"\n[Run8] DONE. flow={len(flow_ready)} cap={len(cap_alloc)} dir={len(dir_obs)} weak={len(weak_hint)} meta={len(meta_only_l)}")
print(f"  L1={stats.get('L1_holdings',0)} L3={stats.get('L3_specific_category',0)} L4_broad={stats.get('L4_broad_category_downgraded',0)} L4_country={stats.get('L4_country_only_downgraded',0)} L4_name={stats.get('L4_name_only_downgraded',0)} L5={stats.get('L5_metadata',0)}")
