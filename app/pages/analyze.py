import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.analysis_service import generate_financial_report_from_materials, report_json_to_markdown, select_analysis_anchor
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.company_profile_service import load_company_profile
from services.repository_service import refresh_company_repository
from utils.file_utils import (
    build_extracted_json_path,
    build_report_json_path,
    build_report_md_path,
    get_parsed_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    save_text_file,
    sort_paths_by_year_and_name,
)


def analyze_financial_report_page():
    st.title("AI 财报分析报告生成")
    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    stored_profile = load_company_profile(company_folder)
    pending_diff = stored_profile.get("pending_auto_profile_diff", {}) or {}
    if pending_diff:
        st.warning("检测到公司画像的自动识别结果与当前手动标签不一致。建议去‘公司画像’页决定是否覆盖。")
    parsed_json_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))
    if not parsed_json_files:
        st.warning("该公司没有 parsed JSON。")
        return

    rows = []
    for parsed_path in parsed_json_files:
        extracted_path = build_extracted_json_path(parsed_path)
        extracted = load_json_file(extracted_path) if Path(extracted_path).exists() else {}
        rows.append({
            "parsed_name": Path(parsed_path).name,
            "parsed_path": parsed_path,
            "extracted_path": extracted_path,
            "period_key": extracted.get("period_key", ""),
            "report_type": extracted.get("report_type", "UNKNOWN"),
            "document_type": extracted.get("document_type", "other_disclosure"),
            "is_primary": extracted.get("is_primary_financial_report", False),
            "forecast_as_of_period": extracted.get("forecast_as_of_period", ""),
            "forecast_target_period": extracted.get("forecast_target_period", ""),
        })
    st.dataframe(rows, width="stretch")
    selected_names = st.multiselect("选择用于分析的 parsed JSON", options=[r["parsed_name"] for r in rows])
    if st.button("开始生成 AI 分析报告"):
        if not selected_names:
            st.warning("请至少选择 1 份 parsed JSON。")
            return
        progress = st.progress(0.0, text="准备材料")
        selected_items = []
        total = len(selected_names) + 2
        for idx, name in enumerate(selected_names, start=1):
            progress.progress(idx / total, text=f"[{idx}/{len(selected_names)}] 载入材料：{name}")
            row = next(r for r in rows if r["parsed_name"] == name)
            if not Path(row["extracted_path"]).exists():
                st.error(f"缺少 extracted：{Path(row['extracted_path']).name}")
                return
            selected_items.append({"row": row, "parsed": load_json_file(row["parsed_path"]), "extracted": load_json_file(row["extracted_path"])})
        try:
            progress.progress((len(selected_names) + 1) / total, text="调用 AI 生成分析 JSON")
            report_data = generate_financial_report_from_materials([i["parsed"] for i in selected_items], [i["extracted"] for i in selected_items])
            anchor_extracted = select_analysis_anchor([i["extracted"] for i in selected_items])
            anchor_item = next((item for item in selected_items if item["extracted"] is anchor_extracted), selected_items[-1])
            report_json_path = build_report_json_path(anchor_item["row"]["extracted_path"])
            report_md_path = build_report_md_path(anchor_item["row"]["extracted_path"])
            report_markdown = report_json_to_markdown(report_data)
            save_json_file(report_data, report_json_path)
            save_text_file(report_markdown, report_md_path)
            refresh_company_repository(company_folder)
            progress.progress(1.0, text="分析报告生成完成")
            st.success("分析报告生成完成。")
            st.markdown(report_markdown)
        except Exception as exc:
            st.error(f"AI 调用或 JSON 修复失败：{exc}")


if __name__ == "__main__":
    analyze_financial_report_page()
