import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.company_profile_service import load_company_profile
from services.repository_service import refresh_company_repository
from services.update_service import generate_updated_master_report, master_report_to_markdown
from utils.file_utils import (
    build_delta_json_path,
    build_extracted_json_path,
    build_history_memory_path,
    build_master_report_path,
    build_report_json_path,
    build_report_md_path,
    get_extracted_json_files_in_company_folder,
    get_parsed_json_files_in_company_folder,
    get_report_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    save_text_file,
    sort_paths_by_year_and_name,
)


def _render_existing_update_outputs(report_json_path: Path, report_md_path: Path, delta_json_path: Path, master_report_path: Path):
    existing = [p for p in [report_json_path, report_md_path, delta_json_path, master_report_path] if p.exists()]
    if not existing:
        st.info("本次 latest parsed 对应的整合输出尚未生成。")
        return False
    st.warning("本次 latest parsed 已存在部分整合输出。若再次执行，可选择覆盖原文件。")
    for path in existing:
        st.write(f"- `{path.name}`")
    return True


def update_financial_report_page():
    st.title("历史报告更新机制（全量事实 + 全量判断版）")
    st.caption("Update 是站在某个信息时点，汇总历史全部事实、历史判断、上一次报告和最新材料，重建一份最新版研究报告；它不是 Forecast 的替代物。")

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
    extracted_json_files = sort_paths_by_year_and_name(get_extracted_json_files_in_company_folder(company_folder))
    report_json_files = sort_paths_by_year_and_name(get_report_json_files_in_company_folder(company_folder))
    if not parsed_json_files:
        st.warning("该公司没有 parsed JSON，请先完成 parse。")
        return

    parsed_options = [Path(path).name for path in parsed_json_files]
    selected_parsed_name = st.selectbox("请选择本次作为最新一期的 parsed JSON", options=[""] + parsed_options, index=0)
    if not selected_parsed_name:
        st.info("请先选择最新一期 parsed 文件。")
        return

    latest_parsed_path = next(path for path in parsed_json_files if Path(path).name == selected_parsed_name)
    latest_extracted_path = build_extracted_json_path(latest_parsed_path)
    st.write(f"最新一期 parsed：`{selected_parsed_name}`")
    st.write(f"自动对应 extracted：`{Path(latest_extracted_path).name}`")
    if not Path(latest_extracted_path).exists():
        st.error("未找到对应的 extracted JSON，请先完成 extract。")
        return

    historical_extracted_paths = [path for path in extracted_json_files if Path(path).resolve() != Path(latest_extracted_path).resolve()]
    current_target_report_path = build_report_json_path(latest_extracted_path)
    historical_report_paths = [path for path in report_json_files if Path(path).resolve() != Path(current_target_report_path).resolve()]
    last_report_path = historical_report_paths[-1] if historical_report_paths else None
    history_memory_path = build_history_memory_path(company_folder)
    previous_history_memory = load_json_file(history_memory_path) if Path(history_memory_path).exists() else {}

    st.write(f"历史 extracted 数量：{len(historical_extracted_paths)}")
    st.write(f"历史 report 数量：{len(historical_report_paths)}")
    st.write(f"上一期报告：{Path(last_report_path).name if last_report_path else '无'}")

    report_json_path = Path(build_report_json_path(latest_extracted_path))
    report_md_path = Path(build_report_md_path(latest_extracted_path))
    delta_json_path = Path(build_delta_json_path(latest_extracted_path))
    master_report_path = Path(build_master_report_path(company_folder))
    exists = _render_existing_update_outputs(report_json_path, report_md_path, delta_json_path, master_report_path)
    confirm_overwrite = True if not exists else st.checkbox("我确认覆盖本次整合输出文件", value=False)

    if st.button("开始生成最新版整合报告", disabled=(exists and not confirm_overwrite)):
        progress = st.progress(0.0, text="准备载入历史材料")
        latest_parsed = load_json_file(latest_parsed_path)
        latest_extracted = load_json_file(latest_extracted_path)
        progress.progress(0.2, text="载入历史 extracted")
        historical_extracted_list = [load_json_file(path) for path in historical_extracted_paths]
        progress.progress(0.4, text="载入历史 report")
        historical_report_list = [load_json_file(path) for path in historical_report_paths]
        last_report = load_json_file(last_report_path) if last_report_path else {}
        try:
            progress.progress(0.65, text="调用 AI 生成 master_report / delta_report")
            result = generate_updated_master_report(
                latest_parsed=latest_parsed,
                latest_extracted=latest_extracted,
                historical_extracted_list=historical_extracted_list,
                historical_report_list=historical_report_list,
                last_report=last_report,
                previous_history_memory=previous_history_memory,
            )
            master_report = result["master_report"]
            delta_report = result["delta_report"]
            history_memory = result["history_memory"]
            report_markdown = master_report_to_markdown(master_report)
            progress.progress(0.85, text="写入 JSON / Markdown")
            save_json_file(master_report, report_json_path)
            save_json_file(master_report, master_report_path)
            save_text_file(report_markdown, report_md_path)
            save_json_file(delta_report, delta_json_path)
            save_json_file(history_memory, history_memory_path)
            refresh_company_repository(company_folder)
            progress.progress(1.0, text="最新版整合报告生成完成")
            st.success("最新版整合报告生成完成！")
            st.subheader("最新版主报告预览")
            st.markdown(report_markdown)
            st.subheader("变化摘要（delta）")
            st.json(delta_report)
        except Exception as exc:
            st.error(f"Update 生成失败：{exc}")


if __name__ == "__main__":
    update_financial_report_page()
