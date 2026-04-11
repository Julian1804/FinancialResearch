import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.repository_service import refresh_company_repository
from services.revision_memory_service import rebuild_history_memory_with_backtest
from services.forecast_service import (
    bsts_runtime_status,
    build_snapshot_actual_auto_compare,
    build_snapshot_auto_match,
    generate_forecast_check,
)
from utils.file_utils import (
    build_extracted_json_path,
    build_forecast_check_json_path,
    get_parsed_json_files_in_company_folder,
    get_report_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    sort_paths_by_year_and_name,
)


def forecast_check_page():
    st.title("预测回测与偏差分析（写回 history_memory 版）")
    st.info(bsts_runtime_status()["message"])

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning("还没有任何公司文件夹。")
        return

    selected_company = st.selectbox(
        "请选择公司",
        options=company_values,
        index=0,
        format_func=format_company_option,
    )
    if not selected_company:
        st.info("请先选择公司。")
        return

    company_folder = get_company_folder_path(selected_company)
    report_json_files = sort_paths_by_year_and_name(get_report_json_files_in_company_folder(company_folder))
    parsed_json_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))

    if not parsed_json_files:
        st.warning("该公司至少需要 parsed JSON。")
        return

    actual_parsed_options = [Path(path).name for path in parsed_json_files]
    selected_actual_parsed_name = st.selectbox("请选择当前观察期 parsed JSON", options=[""] + actual_parsed_options, index=0)
    if not selected_actual_parsed_name:
        st.info("请先选择当前观察期 parsed 文件。")
        return

    selected_actual_parsed_path = next(path for path in parsed_json_files if Path(path).name == selected_actual_parsed_name)
    matched_actual_extracted_path = build_extracted_json_path(selected_actual_parsed_path)
    st.write(f"自动对应 extracted：`{Path(matched_actual_extracted_path).name}`")
    if not Path(matched_actual_extracted_path).exists():
        st.error("未找到当前观察期对应的 extracted JSON，请先完成 extract。")
        return

    actual_extracted = load_json_file(matched_actual_extracted_path)
    snapshot_match = build_snapshot_auto_match(company_folder, actual_extracted)

    st.markdown("## 自动匹配 snapshot")
    if snapshot_match.get("matched"):
        snapshot = snapshot_match["snapshot"]
        st.success("已自动匹配到最相关的 forecast snapshot。")
        st.write(f"- metric_name：`{snapshot.get('metric_name', '')}`")
        st.write(f"- forecast_as_of_period：`{snapshot.get('forecast_as_of_period', '')}`")
        st.write(f"- forecast_target_period：`{snapshot.get('forecast_target_period', '')}`")
        st.write(f"- base：`{snapshot.get('scenario_bundle', {}).get('base', {}).get('value')}`")
        st.write(f"- bull：`{snapshot.get('scenario_bundle', {}).get('bull', {}).get('value')}`")
        st.write(f"- bear：`{snapshot.get('scenario_bundle', {}).get('bear', {}).get('value')}`")
        st.write(f"- snapshot_path：`{snapshot.get('snapshot_path', '')}`")
    else:
        snapshot = None
        st.warning(f"未自动匹配到 snapshot：{snapshot_match.get('reason', '')}")

    st.markdown("## 自动实际值对接")
    if snapshot:
        auto_comparison = build_snapshot_actual_auto_compare(company_folder, snapshot, actual_extracted)
        if auto_comparison.get("matched"):
            st.success("已完成 snapshot vs actual 的自动硬数值对比。")
            st.write(f"- comparison_basis：`{auto_comparison.get('comparison_basis', '')}`")
            st.write(f"- actual_value：`{auto_comparison.get('actual_value')}`")
            st.write(f"- expected_base：`{auto_comparison.get('expected_base')}`")
            st.write(f"- expected_bull：`{auto_comparison.get('expected_bull')}`")
            st.write(f"- expected_bear：`{auto_comparison.get('expected_bear')}`")
            st.write(f"- deviation_abs：`{auto_comparison.get('deviation_abs')}`")
            st.write(f"- deviation_pct：`{auto_comparison.get('deviation_pct')}`")
            st.write(f"- prediction_match_level_auto：`{auto_comparison.get('prediction_match_level_auto', '')}`")
            st.write(f"- actual_source_file：`{auto_comparison.get('actual_source_file', '')}`")
        else:
            st.warning(f"未能自动完成硬数值对比：{auto_comparison.get('reason', '')}")
    else:
        auto_comparison = None
        st.info("由于没有匹配到 snapshot，无法自动做硬数值对比。")

    st.markdown("## 基准 report（可选）")
    if report_json_files:
        base_report_options = [Path(path).name for path in report_json_files]
        selected_base_report_name = st.selectbox(
            "请选择基准报告（可选，若不选则仅使用 snapshot + 当前观察期）",
            options=[""] + base_report_options,
            index=0,
        )
        if selected_base_report_name:
            selected_base_report_path = next(path for path in report_json_files if Path(path).name == selected_base_report_name)
            base_report = load_json_file(selected_base_report_path)
        else:
            base_report = {}
    else:
        st.info("当前没有 report JSON，将仅使用 snapshot + 当前观察期进行回测。")
        base_report = {}

    if st.button("开始预测回测与偏差分析"):
        progress = st.progress(0.0, text="载入 actual parsed")
        actual_parsed = load_json_file(selected_actual_parsed_path)
        progress.progress(0.35, text="生成 forecast_check")
        forecast_check = generate_forecast_check(
            base_report=base_report,
            actual_parsed=actual_parsed,
            actual_extracted=actual_extracted,
            snapshot=snapshot,
            auto_comparison=auto_comparison,
        )

        output_path = build_forecast_check_json_path(
            Path(snapshot.get("snapshot_path")) if snapshot and snapshot.get("snapshot_path") else Path(selected_actual_parsed_path),
            matched_actual_extracted_path,
        )
        save_json_file(forecast_check, output_path)
        progress.progress(0.75, text="重建 history_memory 与 revision log")
        revision_result = rebuild_history_memory_with_backtest(company_folder)
        refresh_company_repository(company_folder)
        progress.progress(1.0, text="预测回测完成")

        st.success("预测回测与偏差分析完成！")
        st.info("说明：当前回测页已显示运行进度；真正的强制取消仍需后续引入后台任务队列。")
        st.write(f"forecast_check 已保存到：{output_path}")
        st.write(f"history_memory 已更新：{revision_result.get('history_memory_path', '')}")
        st.write(f"revision log 已更新：{revision_result.get('revision_log_path', '')}")
        st.json(forecast_check)


if __name__ == "__main__":
    forecast_check_page()