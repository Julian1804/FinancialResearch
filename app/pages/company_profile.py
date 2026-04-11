import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_profile_service import get_taxonomy_options, load_company_profile, save_company_profile
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.industry_profile_service import infer_company_industry_metric_profile


def _map_by_code(tag_items: list[dict]) -> dict:
    return {item.get("code", ""): item for item in tag_items if item.get("code")}


def company_profile_page():
    st.title("公司画像与标签")
    st.caption("BM / VC / LC 默认单选，G 多选。公司画像会作为财报分析的先验标签，但手动修改优先级最高。")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹，请先上传资料。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    auto_profile = infer_company_industry_metric_profile(company_folder)
    stored = load_company_profile(company_folder)
    manual = stored.get("manual_override", {}) or {}
    taxonomy = get_taxonomy_options()
    sector_profiles = taxonomy.get("sector_profiles", {})

    bm_map = _map_by_code(taxonomy.get("business_model_tags", []))
    vc_map = _map_by_code(taxonomy.get("value_chain_tags", []))
    lc_map = _map_by_code(taxonomy.get("lifecycle_tags", []))
    g_map = _map_by_code(taxonomy.get("disturbance_tags", []))

    tags = auto_profile.get("tags", {}) or {}
    st.subheader("自动识别结果")
    st.json(auto_profile)

    pending_diff = stored.get("pending_auto_profile_diff", {}) or {}
    if pending_diff and manual.get("enabled"):
        st.warning("检测到系统自动画像与当前手动画像出现差异。建议你核对后决定是否继续保留手动覆盖。")
        st.json(pending_diff)

    with st.form("company_profile_override_form"):
        enabled = st.checkbox("启用手动标签覆盖", value=manual.get("enabled", False))
        profile_names = sorted([key for key in sector_profiles.keys() if key != "default"])
        current_profile_name = manual.get("profile_name") or auto_profile.get("profile_name", "")
        profile_name = st.selectbox("行业模板", options=[""] + profile_names, index=([""] + profile_names).index(current_profile_name) if current_profile_name in ([""] + profile_names) else 0)
        level_1 = st.text_input("一级分类", value=manual.get("level_1", auto_profile.get("level_1", "")))
        level_2 = st.text_input("二级分类", value=manual.get("level_2", auto_profile.get("level_2", "")))
        level_3 = st.text_input("三级分类", value=manual.get("level_3", auto_profile.get("level_3", "")))

        bm_default = manual.get("business_model_primary") or (tags.get("business_model", {}) or {}).get("primary", "")
        vc_default = manual.get("value_chain_primary") or (tags.get("value_chain", {}) or {}).get("primary", "")
        lc_default = manual.get("life_cycle_primary") or (tags.get("life_cycle", {}) or {}).get("primary", "")
        lc_sub_default = manual.get("life_cycle_sub_type") or (tags.get("life_cycle", {}) or {}).get("sub_type", "")
        g_default = manual.get("special_factors") or list(tags.get("special_factors", []) or [])

        business_model_primary = st.selectbox("商业模式（BM，单选）", options=[""] + list(bm_map.keys()), index=([""] + list(bm_map.keys())).index(bm_default) if bm_default in ([""] + list(bm_map.keys())) else 0, format_func=lambda x: f"{x}｜{bm_map.get(x, {}).get('label', '')}" if x else "")
        value_chain_primary = st.selectbox("价值链位势（VC，单选）", options=[""] + list(vc_map.keys()), index=([""] + list(vc_map.keys())).index(vc_default) if vc_default in ([""] + list(vc_map.keys())) else 0, format_func=lambda x: f"{x}｜{vc_map.get(x, {}).get('label', '')}" if x else "")
        life_cycle_primary = st.selectbox("生命周期（LC，单选）", options=[""] + list(lc_map.keys()), index=([""] + list(lc_map.keys())).index(lc_default) if lc_default in ([""] + list(lc_map.keys())) else 0, format_func=lambda x: f"{x}｜{lc_map.get(x, {}).get('label', '')}" if x else "")
        life_cycle_sub_type = st.selectbox("生命周期修饰语（可选）", options=taxonomy.get("lifecycle_subtypes", ["", "早期", "后期"]), index=taxonomy.get("lifecycle_subtypes", ["", "早期", "后期"]).index(lc_sub_default) if lc_sub_default in taxonomy.get("lifecycle_subtypes", ["", "早期", "后期"]) else 0)
        special_factors = st.multiselect("特殊扰动（G，多选）", options=list(g_map.keys()), default=[code for code in g_default if code in g_map], format_func=lambda x: f"{x}｜{g_map.get(x, {}).get('label', '')}")

        recommended_metrics = st.text_area("手动指定优先指标（逗号分隔，可选）", value=", ".join(manual.get("recommended_metrics", auto_profile.get("recommended_metrics", [])[:20])))
        reason = st.text_area("手动覆盖理由", value=manual.get("reason", ""), height=120)
        overwrite_manual_with_latest_auto = st.checkbox("若自动画像与手动画像冲突，保存时用自动画像覆盖手动设置", value=False)
        submitted = st.form_submit_button("保存公司画像")

    if submitted:
        if overwrite_manual_with_latest_auto:
            payload = stored
            payload["manual_override"] = {"enabled": False}
            payload["auto_profile_snapshot"] = auto_profile
            payload["pending_auto_profile_diff"] = {}
            save_company_profile(company_folder, payload)
            st.success("已取消手动覆盖，恢复为最新自动画像。")
            st.rerun()

        payload = {
            "company_name": selected_company,
            "auto_profile_snapshot": auto_profile,
            "pending_auto_profile_diff": {},
            "manual_override": {
                "enabled": enabled,
                "profile_name": profile_name,
                "profile_label": sector_profiles.get(profile_name, {}).get("label", "") if profile_name else "",
                "level_1": level_1,
                "level_2": level_2,
                "level_3": level_3,
                "business_model_primary": business_model_primary,
                "business_model_label": bm_map.get(business_model_primary, {}).get("label", ""),
                "value_chain_primary": value_chain_primary,
                "value_chain_label": vc_map.get(value_chain_primary, {}).get("label", ""),
                "life_cycle_primary": life_cycle_primary,
                "life_cycle_sub_type": life_cycle_sub_type,
                "life_cycle_label": (f"{lc_map.get(life_cycle_primary, {}).get('label', '')}（{life_cycle_sub_type}）" if life_cycle_primary and life_cycle_sub_type else lc_map.get(life_cycle_primary, {}).get("label", "")),
                "special_factors": list(special_factors),
                "factor_labels": [g_map.get(code, {}).get("label", "") for code in special_factors],
                "recommended_metrics": [item.strip() for item in recommended_metrics.split(",") if item.strip()],
                "reason": reason,
            },
        }
        save_company_profile(company_folder, payload)
        st.success("公司画像已保存。后续 Metrics / Analyze / Update 会优先使用手动标签。")

    st.subheader("当前已保存设置")
    st.json(load_company_profile(company_folder))


if __name__ == "__main__":
    company_profile_page()
