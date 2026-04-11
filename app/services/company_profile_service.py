from __future__ import annotations

from pathlib import Path
from typing import Optional

from config.settings import load_industry_metric_profiles
from services.research_utils import now_iso
from utils.file_utils import load_json_file, save_json_file

LIFECYCLE_SUBTYPE_OPTIONS = ["", "早期", "后期"]


def _build_company_profile_path(company_folder: str | Path) -> Path:
    company_folder = Path(company_folder)
    analysis_dir = company_folder / "年报分析"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir / "company_profile.json"


def load_company_profile(company_folder: str | Path) -> dict:
    path = _build_company_profile_path(company_folder)
    if path.exists():
        payload = load_json_file(path)
        payload.setdefault("manual_override", {"enabled": False})
        payload.setdefault("auto_profile_snapshot", {})
        payload.setdefault("pending_auto_profile_diff", {})
        return payload
    return {
        "company_name": Path(company_folder).name,
        "manual_override": {"enabled": False},
        "auto_profile_snapshot": {},
        "pending_auto_profile_diff": {},
        "updated_at": "",
    }


def save_company_profile(company_folder: str | Path, payload: dict) -> dict:
    path = _build_company_profile_path(company_folder)
    payload = payload or {}
    payload["company_name"] = Path(company_folder).name
    payload["updated_at"] = now_iso()
    save_json_file(payload, path)
    return payload


def get_taxonomy_options() -> dict:
    payload = load_industry_metric_profiles() or {}
    taxonomy = payload.get("taxonomy", {})
    sector_profiles = payload.get("sector_profiles", {})
    return {
        "sector_profiles": sector_profiles,
        "business_model_tags": taxonomy.get("business_model_tags", []),
        "value_chain_tags": taxonomy.get("value_chain_tags", []),
        "lifecycle_tags": taxonomy.get("lifecycle_tags", []),
        "disturbance_tags": taxonomy.get("disturbance_tags", []),
        "lifecycle_subtypes": LIFECYCLE_SUBTYPE_OPTIONS,
    }


def _first_code(values: list[str] | None) -> str:
    if not values:
        return ""
    first = values[0]
    if not first:
        return ""
    return str(first).split(":", 1)[0].strip()


def _first_label(values: list[str] | None) -> str:
    if not values:
        return ""
    first = str(values[0])
    if ":" in first:
        return first.split(":", 1)[1].strip()
    return first


def _normalize_manual_override(manual_override: Optional[dict], auto_profile: Optional[dict] = None) -> dict:
    manual_override = dict(manual_override or {})
    auto_profile = dict(auto_profile or {})
    # backward compatibility from old multiselect structure
    if not manual_override.get("business_model_primary"):
        manual_override["business_model_primary"] = _first_code(manual_override.get("business_model_tags"))
    if not manual_override.get("business_model_label"):
        manual_override["business_model_label"] = _first_label(manual_override.get("business_model_tags"))
    if not manual_override.get("value_chain_primary"):
        manual_override["value_chain_primary"] = _first_code(manual_override.get("value_chain_tags"))
    if not manual_override.get("value_chain_label"):
        manual_override["value_chain_label"] = _first_label(manual_override.get("value_chain_tags"))
    if not manual_override.get("life_cycle_primary"):
        manual_override["life_cycle_primary"] = _first_code(manual_override.get("lifecycle_tags"))
    if not manual_override.get("life_cycle_label"):
        manual_override["life_cycle_label"] = _first_label(manual_override.get("lifecycle_tags"))
    if manual_override.get("life_cycle_sub_type") is None:
        manual_override["life_cycle_sub_type"] = ""
    if not manual_override.get("special_factors") and manual_override.get("disturbance_tags"):
        manual_override["special_factors"] = [str(v).split(":", 1)[0].strip() for v in manual_override.get("disturbance_tags", [])]
        manual_override["factor_labels"] = [str(v).split(":", 1)[1].strip() if ":" in str(v) else str(v) for v in manual_override.get("disturbance_tags", [])]
    if not manual_override.get("recommended_metrics") and auto_profile.get("recommended_metrics"):
        manual_override["recommended_metrics"] = list(auto_profile.get("recommended_metrics", []))
    return manual_override


def _build_tag_summary_from_tags(tags: dict) -> dict:
    out = {"business_model": [], "value_chain": [], "lifecycle": [], "disturbance": []}
    bm = tags.get("business_model", {}) or {}
    vc = tags.get("value_chain", {}) or {}
    lc = tags.get("life_cycle", {}) or {}
    g_codes = tags.get("special_factors", []) or []
    g_labels = tags.get("factor_labels", []) or []
    if bm.get("primary"):
        out["business_model"] = [f"{bm.get('primary')}:{bm.get('label', '')}".rstrip(":")]
    if vc.get("primary"):
        out["value_chain"] = [f"{vc.get('primary')}:{vc.get('label', '')}".rstrip(":")]
    if lc.get("primary"):
        label = lc.get("label", "")
        out["lifecycle"] = [f"{lc.get('primary')}:{label}".rstrip(":")]
    out["disturbance"] = [f"{code}:{label}".rstrip(":") for code, label in zip(g_codes, g_labels)]
    return out


def apply_manual_override(auto_profile: dict, manual_override: dict) -> dict:
    auto_profile = dict(auto_profile or {})
    manual_override = _normalize_manual_override(manual_override, auto_profile)
    if not manual_override.get("enabled"):
        return auto_profile

    effective = dict(auto_profile)
    for key in ["profile_name", "profile_label", "level_1", "level_2", "level_3"]:
        if manual_override.get(key):
            effective[key] = manual_override.get(key)

    tags = {
        "business_model": {
            "primary": manual_override.get("business_model_primary", ""),
            "label": manual_override.get("business_model_label", ""),
        },
        "value_chain": {
            "primary": manual_override.get("value_chain_primary", ""),
            "label": manual_override.get("value_chain_label", ""),
        },
        "life_cycle": {
            "primary": manual_override.get("life_cycle_primary", ""),
            "sub_type": manual_override.get("life_cycle_sub_type", ""),
            "label": manual_override.get("life_cycle_label", ""),
        },
        "special_factors": list(manual_override.get("special_factors", []) or []),
        "factor_labels": list(manual_override.get("factor_labels", []) or []),
    }
    effective["tags"] = tags
    effective["tag_summary"] = _build_tag_summary_from_tags(tags)

    if manual_override.get("recommended_metrics"):
        effective["recommended_metrics"] = list(manual_override.get("recommended_metrics", []))
    effective["override_source"] = "manual"
    effective["override_reason"] = manual_override.get("reason", "")
    return effective


def _profile_diff(prev_auto: dict, new_auto: dict) -> dict:
    keys = ["profile_name", "level_1", "level_2", "level_3", "tags", "recommended_metrics"]
    diff = {}
    for key in keys:
        if (prev_auto or {}).get(key) != (new_auto or {}).get(key):
            diff[key] = {"old": (prev_auto or {}).get(key), "new": (new_auto or {}).get(key)}
    return diff


def refresh_company_profile_snapshot(
    company_folder: str | Path,
    auto_profile: dict,
    *,
    overwrite_manual: bool = False,
    refresh_reason: str = "",
) -> dict:
    stored = load_company_profile(company_folder)
    manual = _normalize_manual_override(stored.get("manual_override", {}), auto_profile)
    prev_auto = stored.get("auto_profile_snapshot", {}) or {}
    diff = _profile_diff(prev_auto, auto_profile)
    stored["auto_profile_snapshot"] = auto_profile
    stored["last_auto_refresh_reason"] = refresh_reason
    stored["last_auto_refresh_at"] = now_iso()
    if manual.get("enabled") and diff:
        stored["pending_auto_profile_diff"] = diff
        if overwrite_manual:
            stored["manual_override"] = {"enabled": False}
            stored["pending_auto_profile_diff"] = {}
    else:
        stored["pending_auto_profile_diff"] = {}
    save_company_profile(company_folder, stored)
    return stored
