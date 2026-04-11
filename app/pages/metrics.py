import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.metric_extraction_service import (
    extract_standardized_metrics,
    load_standardized_metrics,
    merge_selected_metrics_to_registry,
)
from services.repository_service import refresh_company_repository


def _build_default_selection_rows(candidates: list[dict]) -> list[dict]:
    grouped = {}
    for item in candidates:
        period_key = item.get("period_key", "")
        if not period_key or not (item.get("allow_into_actuals") or item.get("is_primary_financial_report")):
            continue
        grouped.setdefault(period_key, []).append(item)

    rows = []
    for period_key, items in grouped.items():
        items = sorted(
            items,
            key=lambda x: (
                1 if x.get("allow_into_actuals") else 0,
                x.get("score", 0),
                x.get("material_timestamp", ""),
            ),
            reverse=True,
        )
        best = items[0]
        rows.append({
            "period_key": best.get("period_key", ""),
            "report_type": best.get("period_key", "")[-2:] if best.get("period_key", "") else "",
            "source_file": best.get("source_file", ""),
            "material_timestamp": best.get("material_timestamp", ""),
            "value": best.get("value"),
            "unit": best.get("unit", ""),
            "notes": f"{best.get('raw_label', '')} | {best.get('document_type', '')}",
        })
    rows.sort(key=lambda x: x.get("period_key", ""))
    return rows


def _render_profile(profile: dict):
    if not profile:
        return
    st.caption(
        f"行业标签画像：{profile.get('profile_label', '通用')} | 来源={profile.get('override_source', 'auto')} | "
        f"{profile.get('level_1', '信息不足')} / {profile.get('level_2', '信息不足')} / {profile.get('level_3', '信息不足')} | "
        f"keyword_hit_score={profile.get('keyword_hit_score', 0)}"
    )
    if profile.get("candidate_profiles"):
        st.write(
            "候选行业：",
            "；".join([f"{item.get('profile_label')}({item.get('score')})" for item in profile.get("candidate_profiles", [])[:5]]),
        )

    tag_summary = profile.get("tag_summary", {}) or {}
    if tag_summary.get("business_model"):
        st.write("商业模式：", "；".join(tag_summary.get("business_model", [])))
    if tag_summary.get("value_chain"):
        st.write("价值链位势：", "；".join(tag_summary.get("value_chain", [])))
    if tag_summary.get("lifecycle"):
        st.write("生命周期：", "；".join(tag_summary.get("lifecycle", [])))
    if tag_summary.get("disturbance"):
        st.write("特殊扰动：", "；".join(tag_summary.get("disturbance", [])))

    if profile.get("recommended_metrics"):
        st.write("推荐优先关注指标：", "、".join(profile.get("recommended_metrics", [])[:18]))


def metrics_page():
    st.title("标准化财务指标抽取")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹，请先上传、解析并提取资料。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("执行自动指标抽取", type="primary"):
            with st.spinner("正在扫描 parsed / extracted 并生成标准化指标候选..."):
                result = extract_standardized_metrics(company_folder)
                refresh_company_repository(company_folder)
            st.success(f"抽取完成：候选数={result.get('total_candidate_count', 0)}，指标={', '.join(result.get('metric_names', [])) or '无'}")
    with col2:
        if st.button("重新读取抽取结果"):
            st.rerun()

    extracted_data = load_standardized_metrics(company_folder)
    metrics = extracted_data.get("metrics", {})
    industry_profile = extracted_data.get("industry_metric_profile", {})
    _render_profile(industry_profile)

    if not metrics:
        st.info("当前还没有标准化指标结果。请先点击“执行自动指标抽取”。")
        return

    metric_names = sorted(list(metrics.keys()))
    selected_metric = st.selectbox("请选择标准化指标", options=metric_names, index=0)
    candidates = metrics.get(selected_metric, [])

    candidate_rows = []
    for idx, item in enumerate(candidates, start=1):
        candidate_rows.append({
            "candidate_id": idx,
            "metric_name": item.get("metric_name", ""),
            "period_key": item.get("period_key", ""),
            "value": item.get("value"),
            "unit": item.get("unit", ""),
            "score": item.get("score"),
            "source_file": item.get("source_file", ""),
            "document_type": item.get("document_type", ""),
            "source_role": item.get("source_role", ""),
            "allow_into_actuals": item.get("allow_into_actuals", False),
            "material_timestamp": item.get("material_timestamp", ""),
            "raw_label": item.get("raw_label", ""),
            "snippet": item.get("snippet", ""),
        })
    st.dataframe(pd.DataFrame(candidate_rows), width="stretch")

    recommended_rows = _build_default_selection_rows(candidates)
    rec_df = pd.DataFrame(recommended_rows)
    if rec_df.empty:
        st.info("当前指标没有可写回主时序的候选值。")
        return

    edited_df = st.data_editor(
        rec_df,
        width="stretch",
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "period_key": st.column_config.TextColumn("period_key"),
            "report_type": st.column_config.TextColumn("report_type"),
            "source_file": st.column_config.TextColumn("source_file"),
            "material_timestamp": st.column_config.TextColumn("material_timestamp"),
            "value": st.column_config.NumberColumn("value"),
            "unit": st.column_config.TextColumn("unit"),
            "notes": st.column_config.TextColumn("notes"),
        },
    )

    if st.button("写回 metric_series_registry.json"):
        rows = edited_df.to_dict(orient="records")
        payload = merge_selected_metrics_to_registry(company_folder=company_folder, selections={selected_metric: rows})
        st.success(f"已写回指标：{selected_metric}")
        st.json(payload)


if __name__ == "__main__":
    metrics_page()
