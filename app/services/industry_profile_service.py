from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from config.settings import load_industry_metric_profiles
from services.research_utils import normalize_whitespace
from utils.file_utils import get_extracted_json_files_in_company_folder, load_json_file, get_company_folder
from services.company_profile_service import apply_manual_override, load_company_profile


def _load_taxonomy() -> dict:
    payload = load_industry_metric_profiles() or {}
    return {
        "taxonomy": payload.get("taxonomy", {}),
        "sector_profiles": payload.get("sector_profiles", payload),
    }


def _build_corpus_from_extracted_materials(extracted_materials: Iterable[dict]) -> str:
    parts: List[str] = []
    for data in extracted_materials:
        if not isinstance(data, dict):
            continue
        parts.extend([
            data.get("company_name", ""),
            data.get("source_file", ""),
            " ".join(data.get("title_candidates", [])[:8]) if isinstance(data.get("title_candidates"), list) else "",
            data.get("summary_preview", ""),
        ])
        key_sections = data.get("key_sections", {})
        if isinstance(key_sections, dict):
            for value in key_sections.values():
                if isinstance(value, str):
                    parts.append(value)
    return normalize_whitespace("\n".join(parts)).lower()


def _build_corpus_from_company_folder(company_folder: str | Path) -> str:
    extracted_files = get_extracted_json_files_in_company_folder(company_folder)
    materials = []
    for path in extracted_files[:30]:
        try:
            materials.append(load_json_file(path))
        except Exception:
            continue
    return _build_corpus_from_extracted_materials(materials)


def _score_keywords(corpus: str, keywords: List[str]) -> int:
    score = 0
    for keyword in keywords or []:
        if keyword and keyword.lower() in corpus:
            score += 1
    return score


def _pick_profile(corpus: str, sector_profiles: Dict[str, dict]) -> tuple[str, dict, list]:
    default_profile = sector_profiles.get("default", {"label": "通用", "recommended_metrics": [], "aliases": {}})
    best_name = "default"
    best_profile = default_profile
    best_score = -1
    ranking = []

    for name, profile in sector_profiles.items():
        if name == "default":
            continue
        score = _score_keywords(corpus, profile.get("keywords", []))
        if score > 0:
            ranking.append({
                "profile_name": name,
                "profile_label": profile.get("label", name),
                "score": score,
                "level_1": profile.get("level_1", "信息不足"),
                "level_2": profile.get("level_2", "信息不足"),
                "level_3": profile.get("level_3", "信息不足"),
            })
        if score > best_score:
            best_name, best_profile, best_score = name, profile, score

    if best_score <= 0:
        best_name, best_profile, best_score = "default", default_profile, 0

    ranking.sort(key=lambda x: x["score"], reverse=True)
    return best_name, best_profile, ranking[:5]


def _pick_single_tag(corpus: str, tag_items: List[dict], default_codes: List[str] | None = None) -> dict:
    scored = []
    for item in tag_items or []:
        score = _score_keywords(corpus, item.get("keywords", []))
        if score > 0:
            scored.append({**item, "score": score})
    if not scored and default_codes:
        code_set = set(default_codes)
        for item in tag_items or []:
            if item.get("code") in code_set:
                scored.append({**item, "score": 0})
                break
    scored.sort(key=lambda x: (x.get("score", 0), x.get("code", "")), reverse=True)
    return scored[0] if scored else {}


def _pick_multi_tags(corpus: str, tag_items: List[dict], default_codes: List[str] | None = None, top_n: int = 3) -> List[dict]:
    scored = []
    for item in tag_items or []:
        score = _score_keywords(corpus, item.get("keywords", []))
        if score > 0:
            scored.append({**item, "score": score})
    if not scored and default_codes:
        code_set = set(default_codes)
        for item in tag_items or []:
            if item.get("code") in code_set:
                scored.append({**item, "score": 0})
    scored.sort(key=lambda x: (x.get("score", 0), x.get("code", "")), reverse=True)
    return scored[:top_n]


def _infer_lifecycle_subtype(corpus: str, lifecycle_code: str) -> str:
    if lifecycle_code == "LC-02":
        if any(token in corpus for token in ["free cash flow positive", "自由现金流转正", "经营现金流转正", "cash flow positive"]):
            return "后期"
        if any(token in corpus for token in ["融资", "亏损扩大", "burn", "持续亏损", "依赖融资"]):
            return "早期"
    if lifecycle_code == "LC-03":
        if any(token in corpus for token in ["回购", "分红", "高比例分红", "payout", "dividend"]):
            return "后期"
        if any(token in corpus for token in ["roe", "高回报", "稳健增长", "利润率稳定"]):
            return "早期"
    return ""


def _merge_recommended_metrics(profile: dict, tags: dict, disturbance_tags: List[dict]) -> List[str]:
    ordered = []
    seen = set()
    for metric in profile.get("recommended_metrics", []):
        if metric not in seen:
            seen.add(metric)
            ordered.append(metric)

    focus_map = {
        "毛利率": "gross_margin",
        "存货周转": "inventory",
        "产能利用率": "utilization_rate",
        "渠道库存": "inventory",
        "订单获取": "order_backlog",
        "收入确认节点": "contract_assets",
        "应收账款账龄": "accounts_receivable",
        "质保金": "guarantee_deposit",
        "合同负债/预收款": "contract_liabilities",
        "人效": "customer_count",
        "续约率/流失率": "customer_count",
        "折旧摊销": "ebitda",
        "利息保障倍数": "total_debt",
        "资产周转率": "revenue",
        "研发资本化": "r_and_d_expense",
        "里程碑付款节奏": "milestone_income",
        "增长质量": "accounts_receivable",
        "分红率": "operating_cash_flow",
        "减值风险": "inventory",
        "资本开支": "capex",
        "固定资产": "capex",
    }

    tag_objects = [tags.get("business_model", {}), tags.get("value_chain", {}), tags.get("life_cycle", {})] + list(disturbance_tags)
    for item in tag_objects:
        for focus in item.get("ai_focus", []) + item.get("analysis_focus", []) + item.get("check_focus", []) + item.get("signals", []):
            metric = focus_map.get(focus)
            if metric and metric not in seen:
                seen.add(metric)
                ordered.append(metric)
    return ordered


def _build_tags_payload(bm: dict, vc: dict, lc: dict, lc_sub_type: str, gs: List[dict]) -> dict:
    lc_label = lc.get("label", "")
    if lc_label and lc_sub_type:
        lc_label = f"{lc_label}（{lc_sub_type}）"
    return {
        "business_model": {"primary": bm.get("code", ""), "label": bm.get("label", "")},
        "value_chain": {"primary": vc.get("code", ""), "label": vc.get("label", "")},
        "life_cycle": {"primary": lc.get("code", ""), "sub_type": lc_sub_type, "label": lc_label or lc.get("label", "")},
        "special_factors": [item.get("code", "") for item in gs],
        "factor_labels": [item.get("label", "") for item in gs],
    }


def _build_tag_summary(tags: dict) -> dict:
    summary = {"business_model": [], "value_chain": [], "lifecycle": [], "disturbance": []}
    bm = tags.get("business_model", {}) or {}
    vc = tags.get("value_chain", {}) or {}
    lc = tags.get("life_cycle", {}) or {}
    if bm.get("primary"):
        summary["business_model"] = [f"{bm.get('primary')}:{bm.get('label', '')}".rstrip(":")]
    if vc.get("primary"):
        summary["value_chain"] = [f"{vc.get('primary')}:{vc.get('label', '')}".rstrip(":")]
    if lc.get("primary"):
        summary["lifecycle"] = [f"{lc.get('primary')}:{lc.get('label', '')}".rstrip(":")]
    summary["disturbance"] = [f"{code}:{label}".rstrip(":") for code, label in zip(tags.get("special_factors", []), tags.get("factor_labels", []))]
    return summary


def infer_profile_from_corpus(corpus: str) -> dict:
    payload = _load_taxonomy()
    taxonomy = payload.get("taxonomy", {})
    sector_profiles = payload.get("sector_profiles", {})

    profile_name, profile, candidates = _pick_profile(corpus, sector_profiles)
    bm = _pick_single_tag(corpus, taxonomy.get("business_model_tags", []), profile.get("default_business_model_tags", []))
    vc = _pick_single_tag(corpus, taxonomy.get("value_chain_tags", []), profile.get("default_value_chain_tags", []))
    lc = _pick_single_tag(corpus, taxonomy.get("lifecycle_tags", []), profile.get("default_lifecycle_tags", []))
    gs = _pick_multi_tags(corpus, taxonomy.get("disturbance_tags", []), profile.get("default_disturbance_tags", []), top_n=4)
    lc_sub_type = _infer_lifecycle_subtype(corpus, lc.get("code", ""))
    tags = _build_tags_payload(bm, vc, lc, lc_sub_type, gs)

    return {
        "profile_name": profile_name,
        "profile_label": profile.get("label", profile_name),
        "level_1": profile.get("level_1", "信息不足"),
        "level_2": profile.get("level_2", "信息不足"),
        "level_3": profile.get("level_3", "信息不足"),
        "keyword_hit_score": candidates[0]["score"] if candidates else 0,
        "candidate_profiles": candidates,
        "aliases": profile.get("aliases", {}),
        "tags": tags,
        "tag_summary": _build_tag_summary(tags),
        "recommended_metrics": _merge_recommended_metrics(profile, tags, gs),
    }


def _boost_profile_by_financial_signals(profile: dict, corpus: str) -> dict:
    profile = dict(profile or {})
    corpus = corpus or ""
    if any(token in corpus for token in ["crdmo", "cdmo", "biologics", "产能", "厂房", "facility", "property, plant and equipment", "depreciation", "capex", "manufacturing", "生产基地"]):
        tags = dict(profile.get("tags", {}) or {})
        vc = dict(tags.get("value_chain", {}) or {})
        if vc.get("primary") != "VC-03":
            tags["value_chain"] = {"primary": "VC-03", "label": "重资产/高壁垒"}
            profile["tags"] = tags
            profile["tag_summary"] = _build_tag_summary({**tags, "special_factors": tags.get("special_factors", []), "factor_labels": tags.get("factor_labels", [])})
    return profile


def infer_profile_from_extracted_materials(extracted_materials: Iterable[dict]) -> dict:
    corpus = _build_corpus_from_extracted_materials(extracted_materials)
    auto_profile = _boost_profile_by_financial_signals(infer_profile_from_corpus(corpus), corpus)
    company_name = ""
    for item in extracted_materials:
        if isinstance(item, dict) and item.get("company_name"):
            company_name = item.get("company_name")
            break
    if company_name:
        try:
            company_folder = get_company_folder(company_name)
            return apply_manual_override(auto_profile, load_company_profile(company_folder).get("manual_override", {}))
        except Exception:
            return auto_profile
    return auto_profile


def infer_company_industry_metric_profile(company_folder: str | Path) -> dict:
    corpus = _build_corpus_from_company_folder(company_folder)
    auto_profile = _boost_profile_by_financial_signals(infer_profile_from_corpus(corpus), corpus)
    return apply_manual_override(auto_profile, load_company_profile(company_folder).get("manual_override", {}))
