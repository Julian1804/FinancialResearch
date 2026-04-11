import sys
import time
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.analysis_service import generate_financial_report_from_materials, report_json_to_markdown, select_analysis_anchor
from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.extractor_service import build_extracted_output
from services.metric_extraction_service import extract_standardized_metrics
from services.actual_metric_service import build_actual_metric_registry
from services.parser_service import build_parsed_output, save_parsed_json
from services.repository_service import refresh_company_repository
from services.task_runtime_service import (
    append_task_log,
    create_task,
    get_task,
    is_task_active,
    is_task_terminal,
    launch_background_task,
    mark_cancelled,
    mark_progress,
    mark_success,
    request_cancel,
    task_should_cancel,
)
from utils.file_utils import (
    build_extracted_json_path,
    build_parsed_json_path,
    build_report_json_path,
    build_report_md_path,
    get_pdf_files_in_company_folder,
    get_parsed_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    save_text_file,
    sort_paths_by_year_and_name,
)

PDF_KEY = "formal_workbench_pdf_selection"
PARSED_KEY = "formal_workbench_parsed_selection"
COMPANY_KEY = "formal_workbench_company"
INGEST_TASK_KEY = "formal_workbench_ingest_task_id"
ANALYZE_TASK_KEY = "formal_workbench_analyze_task_id"
LAST_COMPANY_KEY = "formal_workbench_last_company"


def _clear_selection_state():
    st.session_state[PDF_KEY] = []
    st.session_state[PARSED_KEY] = []


def _on_company_change():
    current = st.session_state.get(COMPANY_KEY, "")
    last = st.session_state.get(LAST_COMPANY_KEY, "")
    if current != last:
        _clear_selection_state()
        st.session_state[LAST_COMPANY_KEY] = current


def _sanitize_multiselect_state(key: str, options: list[str]):
    current = st.session_state.get(key, []) or []
    st.session_state[key] = [item for item in current if item in options]


def _run_ingest_task(task_id: str, company_name: str, company_folder: str, selected_pdfs: list[str]):
    pdf_files = get_pdf_files_in_company_folder(company_folder)
    name_to_path = {Path(path).name: path for path in pdf_files}
    total_steps = max(1, len(selected_pdfs) * 2 + 2)
    done = 0

    for idx, pdf_name in enumerate(selected_pdfs, start=1):
        if task_should_cancel(task_id):
            mark_cancelled(task_id, '一键入库已取消')
            return
        pdf_path = name_to_path.get(pdf_name)
        if not pdf_path:
            append_task_log(task_id, f'跳过不存在文件: {pdf_name}')
            continue

        mark_progress(task_id, done / total_steps, f'[{idx}/{len(selected_pdfs)}] Parse：{pdf_name}')
        append_task_log(task_id, f'开始 Parse: {pdf_name}')
        def _parse_progress(done_steps: int, total_steps_inner: int, message: str):
            append_task_log(task_id, f"{Path(pdf_name).name}｜{message}")
        parsed = build_parsed_output(company_name=company_name, file_path=pdf_path, progress_callback=_parse_progress)
        parsed_path = build_parsed_json_path(pdf_path)
        save_parsed_json(parsed, parsed_path)
        done += 1

        if task_should_cancel(task_id):
            mark_cancelled(task_id, '一键入库已取消')
            return

        mark_progress(task_id, done / total_steps, f'[{idx}/{len(selected_pdfs)}] Extract：{pdf_name}')
        append_task_log(task_id, f'开始 Extract: {pdf_name}')
        extracted = build_extracted_output(parsed)
        extracted_path = build_extracted_json_path(parsed_path)
        save_json_file(extracted, extracted_path)
        done += 1

    if task_should_cancel(task_id):
        mark_cancelled(task_id, '一键入库已取消')
        return

    mark_progress(task_id, done / total_steps, 'Metrics：生成标准化指标')
    append_task_log(task_id, '开始 Metrics')
    extract_standardized_metrics(company_folder)
    done += 1

    if task_should_cancel(task_id):
        mark_cancelled(task_id, '一键入库已取消')
        return

    mark_progress(task_id, done / total_steps, 'Actuals：生成主时序实际值')
    append_task_log(task_id, '开始 Actuals')
    build_actual_metric_registry(company_folder)
    done += 1
    refresh_company_repository(company_folder)
    append_task_log(task_id, '刷新资料总览')
    mark_success(task_id, result={'company_name': company_name, 'pdfs': selected_pdfs}, message='一键入库完成')


def _run_analyze_task(task_id: str, company_name: str, company_folder: str, selected_parsed_names: list[str]):
    parsed_json_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))
    name_to_path = {Path(path).name: path for path in parsed_json_files}
    selected_items = []
    total = max(1, len(selected_parsed_names) + 3)
    step = 0

    for i, name in enumerate(selected_parsed_names, start=1):
        if task_should_cancel(task_id):
            mark_cancelled(task_id, '分析报告生成已取消')
            return
        mark_progress(task_id, step / total, f'[{i}/{len(selected_parsed_names)}] 校验材料：{name}')
        append_task_log(task_id, f'校验材料: {name}')
        parsed_path = name_to_path.get(name)
        if not parsed_path:
            raise FileNotFoundError(f'找不到 parsed 文件: {name}')
        extracted_path = build_extracted_json_path(parsed_path)
        if not Path(extracted_path).exists():
            raise FileNotFoundError(f'{name} 尚未有 extracted JSON')
        selected_items.append({
            'parsed_path': parsed_path,
            'parsed': load_json_file(parsed_path),
            'extracted': load_json_file(extracted_path),
            'extracted_path': extracted_path,
        })
        step += 1

    if task_should_cancel(task_id):
        mark_cancelled(task_id, '分析报告生成已取消')
        return

    mark_progress(task_id, step / total, '调用 AI 生成研究报告')
    append_task_log(task_id, '开始调用 AI')
    report_data = generate_financial_report_from_materials(
        [item['parsed'] for item in selected_items],
        [item['extracted'] for item in selected_items],
    )
    step += 1

    anchor_extracted = select_analysis_anchor([item['extracted'] for item in selected_items])
    anchor_item = next((item for item in selected_items if item['extracted'] is anchor_extracted), selected_items[-1])
    report_json_path = build_report_json_path(anchor_item['extracted_path'])
    report_md_path = build_report_md_path(anchor_item['extracted_path'])
    report_markdown = report_json_to_markdown(report_data)

    if task_should_cancel(task_id):
        mark_cancelled(task_id, '分析报告生成已取消')
        return

    mark_progress(task_id, step / total, '写入 report JSON / Markdown')
    save_json_file(report_data, report_json_path)
    save_text_file(report_markdown, report_md_path)
    refresh_company_repository(company_folder)
    step += 1
    append_task_log(task_id, f'生成报告: {Path(report_json_path).name}')
    mark_success(
        task_id,
        result={
            'company_name': company_name,
            'report_json_path': str(report_json_path),
            'report_md_path': str(report_md_path),
            'report_markdown_preview': report_markdown[:4000],
        },
        message='分析报告生成完成',
    )


def _render_task_panel(title: str, task_id: str | None, session_key: str):
    task = get_task(task_id) if task_id else None
    if not task:
        return False

    st.markdown(f'**{title}**')
    st.progress(float(task.get('progress', 0.0) or 0.0), text=task.get('message', ''))
    status = task.get('status', '')
    if status == 'success':
        st.success(task.get('message', '完成'))
    elif status == 'failed':
        st.error(task.get('error', '') or task.get('message', '执行失败'))
    elif status == 'cancelled':
        st.warning(task.get('message', '已取消'))
    else:
        st.info(f"状态：{status}｜{task.get('message', '')}")

    cols = st.columns([1, 1, 3])
    with cols[0]:
        if is_task_active(task):
            if st.button('取消', key=f'cancel_{task_id}'):
                request_cancel(task_id)
                st.rerun()
    with cols[1]:
        if st.button('刷新状态', key=f'refresh_{task_id}'):
            st.rerun()
    with cols[2]:
        if is_task_terminal(task):
            if st.button('清除任务显示', key=f'clear_{task_id}'):
                st.session_state.pop(session_key, None)
                st.rerun()

    with st.expander('查看运行日志', expanded=False):
        logs = task.get('logs', []) or []
        if logs:
            st.code('\n'.join(logs[-50:]), language='text')
        else:
            st.caption('暂无日志。')

    if status == 'success' and task.get('result', {}).get('report_md_path'):
        md_path = task['result']['report_md_path']
        st.caption(f'生成 Markdown：{md_path}')
        preview = task.get('result', {}).get('report_markdown_preview', '')
        if preview:
            with st.expander('查看报告预览', expanded=False):
                st.markdown(preview)

    if is_task_terminal(task):
        _clear_selection_state()

    return is_task_active(task)


def formal_workbench_page():
    st.title('正式版工作台')
    st.caption('操作上简化；后台逻辑仍沿用现有解析、提取、指标、分析链路。现在改为后台任务模式：可查看进度并协作式取消。')

    company_values = get_company_select_values()
    if len(company_values) <= 1:
        st.warning('还没有任何公司文件夹，请先上传财报。')
        return

    st.session_state.setdefault(COMPANY_KEY, '')
    st.session_state.setdefault(LAST_COMPANY_KEY, '')
    st.session_state.setdefault(PDF_KEY, [])
    st.session_state.setdefault(PARSED_KEY, [])
    st.session_state.setdefault(INGEST_TASK_KEY, '')
    st.session_state.setdefault(ANALYZE_TASK_KEY, '')

    ingest_task = get_task(st.session_state.get(INGEST_TASK_KEY)) if st.session_state.get(INGEST_TASK_KEY) else None
    analyze_task = get_task(st.session_state.get(ANALYZE_TASK_KEY)) if st.session_state.get(ANALYZE_TASK_KEY) else None
    has_active_task = is_task_active(ingest_task) or is_task_active(analyze_task)

    current_val = st.session_state.get(COMPANY_KEY, '')
    if current_val not in company_values:
        st.session_state[COMPANY_KEY] = company_values[0]
        st.session_state[LAST_COMPANY_KEY] = company_values[0]

    st.selectbox(
        '请选择公司',
        options=company_values,
        format_func=format_company_option,
        key=COMPANY_KEY,
        on_change=_on_company_change,
        disabled=has_active_task,
    )
    selected_company = st.session_state.get(COMPANY_KEY, '')
    if not selected_company:
        st.info('请先选择公司。')
        return

    company_folder = get_company_folder_path(selected_company)

    top_cols = st.columns([1, 1, 4])
    with top_cols[0]:
        if st.button('清空本页选择', disabled=has_active_task):
            _clear_selection_state()
            st.rerun()
    with top_cols[1]:
        if st.button('刷新任务状态'):
            st.rerun()
    with top_cols[2]:
        st.caption('说明：取消为协作式取消。当前步骤会先执行完，再在下一步前停止。主线程不再长时间阻塞，因此可以随时取消。')

    active1 = _render_task_panel('步骤 A 当前任务', st.session_state.get(INGEST_TASK_KEY), INGEST_TASK_KEY) if ingest_task else False
    active2 = _render_task_panel('步骤 B 当前任务', st.session_state.get(ANALYZE_TASK_KEY), ANALYZE_TASK_KEY) if analyze_task else False

    with st.expander('步骤 A：一键入库（Parse → Extract → Metrics → Actuals）', expanded=True):
        pdf_files = get_pdf_files_in_company_folder(company_folder)
        pdf_options = [Path(path).name for path in pdf_files]
        _sanitize_multiselect_state(PDF_KEY, pdf_options)
        st.multiselect('选择要入库的 PDF', options=pdf_options, key=PDF_KEY, disabled=has_active_task)
        selected_pdfs = st.session_state.get(PDF_KEY, [])
        if st.button('执行一键入库', type='primary', key='formal_ingest', disabled=has_active_task):
            if not selected_pdfs:
                st.warning('请至少选择 1 个 PDF。')
            else:
                task = create_task('formal_ingest', selected_company, payload={'pdfs': selected_pdfs})
                append_task_log(task['task_id'], f'创建任务，文件数: {len(selected_pdfs)}')
                st.session_state[INGEST_TASK_KEY] = task['task_id']
                launch_background_task(task['task_id'], _run_ingest_task, selected_company, str(company_folder), list(selected_pdfs))
                _clear_selection_state()
                st.rerun()

    with st.expander('步骤 B：生成 AI 分析报告', expanded=True):
        parsed_json_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))
        parsed_options = [Path(path).name for path in parsed_json_files]
        _sanitize_multiselect_state(PARSED_KEY, parsed_options)
        st.multiselect('选择喂给 AI 的 parsed JSON', options=parsed_options, key=PARSED_KEY, disabled=has_active_task)
        selected_parsed_names = st.session_state.get(PARSED_KEY, [])
        if st.button('生成分析报告', key='formal_analyze', disabled=has_active_task):
            if not selected_parsed_names:
                st.warning('请至少选择 1 份 parsed JSON。')
            else:
                task = create_task('formal_analyze', selected_company, payload={'parsed_jsons': selected_parsed_names})
                append_task_log(task['task_id'], f'创建任务，材料数: {len(selected_parsed_names)}')
                st.session_state[ANALYZE_TASK_KEY] = task['task_id']
                launch_background_task(task['task_id'], _run_analyze_task, selected_company, str(company_folder), list(selected_parsed_names))
                _clear_selection_state()
                st.rerun()

    st.info('Update、Forecast、Forecast Check、Decision Support 等高级流程仍建议走测试版独立页面，便于追踪中间 JSON 与 debug。')

    if active1 or active2:
        time.sleep(1.0)
        st.rerun()


if __name__ == '__main__':
    formal_workbench_page()
