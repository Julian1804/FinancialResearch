import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from utils.file_utils import build_parsed_json_path, get_pdf_files_in_company_folder, load_json_file
from services.parser_service import build_parsed_output, save_parsed_json
from services.repository_service import refresh_company_repository


def parse_financial_report_page():
    st.title("财报解析（多引擎 + 多模态）")
    st.info("复杂页（图表+文字、扫描页、表格页）现在会优先尝试调用阿里视觉模型；若失败，则自动回退到传统文本。")

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹，请先上传财报。")
        return

    selected_company = st.selectbox("请选择公司", options=company_values, index=0, format_func=format_company_option)
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    pdf_files = get_pdf_files_in_company_folder(company_folder)
    if not pdf_files:
        st.warning("该公司“年报”文件夹下没有 PDF 文件。")
        return

    pdf_options = [Path(path).name for path in pdf_files]
    selected_pdf_name = st.selectbox("请选择要解析的文件", options=[""] + pdf_options, index=0)
    if not selected_pdf_name:
        st.info("请先选择 PDF 文件。")
        return

    selected_pdf_path = next(path for path in pdf_files if Path(path).name == selected_pdf_name)
    output_path = build_parsed_json_path(selected_pdf_path)
    exists = Path(output_path).exists()

    if exists:
        existing = load_json_file(output_path)
        st.warning(f"该文件已存在 parsed JSON：{Path(output_path).name}")
        st.json({
            "page_count": existing.get("page_count", 0),
            "dominant_language": existing.get("dominant_language", ""),
            "engine_summary": existing.get("engine_summary", {}),
            "page_type_summary": existing.get("page_type_summary", {}),
        })
        overwrite = st.checkbox("我确认覆盖原 parsed JSON", value=False)
    else:
        overwrite = True

    if st.button("开始解析", type="primary", disabled=not overwrite):
        with st.spinner("正在执行解析，请稍候..."):
            parsed_data = build_parsed_output(company_name=selected_company, file_path=selected_pdf_path)
            save_parsed_json(parsed_data, output_path)
            refresh_company_repository(company_folder)

        st.success("解析完成！")
        st.write(f"解析结果已保存到：{output_path}")
        st.write(f"页数：{parsed_data['page_count']}")
        st.write(f"全文字符数：{len(parsed_data['full_text'])}")
        st.write(f"全文主语言：{parsed_data['dominant_language']}")
        st.write(f"解析引擎统计：{parsed_data['engine_summary']}")
        st.write(f"页面类型统计：{parsed_data['page_type_summary']}")
        st.write(f"解析策略：{parsed_data.get('parse_strategy_summary', {})}")
        st.subheader("全文预览（前 3000 字符）")
        st.text_area("解析结果预览", parsed_data["full_text"][:3000], height=350)


if __name__ == "__main__":
    parse_financial_report_page()
