import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from utils.file_utils import (
    build_extracted_json_path,
    get_parsed_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    sort_paths_by_year_and_name,
)
from services.extractor_service import build_extracted_output
from services.repository_service import refresh_company_repository


def extract_key_information_page():
    st.title("关键信息提取")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹，请先上传并解析财报。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    parsed_json_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))
    if not parsed_json_files:
        st.warning("该公司还没有 parsed JSON，请先去 parse 页面完成解析。")
        return

    parsed_options = [Path(path).name for path in parsed_json_files]
    selected_parsed_name = st.selectbox("请选择解析结果文件", options=[""] + parsed_options, index=0)
    if not selected_parsed_name:
        st.info("请先选择 parsed 文件。")
        return

    selected_parsed_path = next(path for path in parsed_json_files if Path(path).name == selected_parsed_name)
    output_path = build_extracted_json_path(selected_parsed_path)
    exists = Path(output_path).exists()
    if exists:
        existing = load_json_file(output_path)
        st.warning(f"该文件已存在 extracted JSON：{Path(output_path).name}")
        st.json({
            "period_key": existing.get("period_key", ""),
            "document_type": existing.get("document_type", ""),
            "report_type": existing.get("report_type", ""),
            "forecast_as_of_period": existing.get("forecast_as_of_period", ""),
            "forecast_target_period": existing.get("forecast_target_period", ""),
        })
        overwrite = st.checkbox("我确认覆盖原 extracted JSON", value=False)
    else:
        overwrite = True

    if st.button("开始提取关键信息", disabled=not overwrite, type="primary"):
        with st.spinner("正在提取关键信息，请稍候..."):
            parsed_data = load_json_file(selected_parsed_path)
            extracted_data = build_extracted_output(parsed_data)
            save_json_file(extracted_data, output_path)
            refresh_company_repository(company_folder)

        st.success("关键信息提取完成！")
        st.write(f"提取结果已保存到：{output_path}")
        st.json({
            "company_name": extracted_data.get("company_name", ""),
            "source_file": extracted_data.get("source_file", ""),
            "page_count": extracted_data.get("page_count", 0),
            "dominant_language": extracted_data.get("dominant_language", ""),
            "report_type": extracted_data.get("report_type", ""),
            "period_key": extracted_data.get("period_key", ""),
            "document_type": extracted_data.get("document_type", ""),
            "forecast_target_period": extracted_data.get("forecast_target_period", ""),
        })


if __name__ == "__main__":
    extract_key_information_page()
