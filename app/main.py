import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

st.set_page_config(page_title='Financial Research Assistant', page_icon='📊', layout='wide')


def _home_page():
    st.title('财报分析（正式版 / 测试版）')
    st.markdown(
        """
- **正式版**：面向日常使用，强调流程简化、后台任务、进度与取消。
- **测试版**：保留所有独立页面，便于逐步 debug 与查看中间 JSON。
        """
    )
    st.info('建议：正式版先跑主流程；若遇到异常，再切到测试版逐步定位。')


home = st.Page(lambda: _home_page(), title='首页', icon='🏠')
FORMAL_PAGES = {
    '工作台': st.Page('pages/formal_workbench.py', title='工作台', icon='✅'),
    '公司画像': st.Page('pages/company_profile.py', title='公司画像', icon='🏷️'),
}
TEST_PAGES = {
    'Upload': st.Page('pages/upload.py', title='Upload', icon='📥'),
    'Parse': st.Page('pages/parse.py', title='Parse', icon='📄'),
    'Extract': st.Page('pages/extract.py', title='Extract', icon='🧩'),
    'Metrics': st.Page('pages/metrics.py', title='Metrics', icon='📐'),
    'Metrics Table': st.Page('pages/metrics_table.py', title='Metrics Table', icon='📋'),
    'Actuals': st.Page('pages/actuals.py', title='Actuals', icon='📌'),
    'Analyze': st.Page('pages/analyze.py', title='Analyze', icon='🧠'),
    'Update': st.Page('pages/update.py', title='Update', icon='🔄'),
    'Forecast': st.Page('pages/forecast.py', title='Forecast', icon='📈'),
    'Forecast Dashboard': st.Page('pages/forecast_dashboard.py', title='Forecast Dashboard', icon='📊'),
    'Forecast Check': st.Page('pages/forecast_check.py', title='Forecast Check', icon='✅'),
    'Backtest Dashboard': st.Page('pages/backtest_dashboard.py', title='Backtest Dashboard', icon='📉'),
    'Backtest Report': st.Page('pages/backtest_report.py', title='Backtest Report', icon='📝'),
    'Revision Memory': st.Page('pages/revision_memory.py', title='Revision Memory', icon='🧠'),
    'Master Report': st.Page('pages/master_report.py', title='Master Report', icon='📚'),
    'Summary Report': st.Page('pages/summary_report.py', title='Summary Report', icon='📒'),
    'Decision Support': st.Page('pages/decision_support.py', title='Decision Support', icon='🧭'),
    'QA': st.Page('pages/qa.py', title='QA', icon='💬'),
    'Repository': st.Page('pages/repository.py', title='Repository', icon='🗂️'),
}

try:
    nav = st.navigation({'总览': [home], '正式版': list(FORMAL_PAGES.values()), '测试版': list(TEST_PAGES.values())}, position='sidebar')
    nav.run()
except Exception:
    _home_page()
    st.warning('当前 Streamlit 版本可能不支持分组导航。请升级后再使用完整正式版/测试版分组。')
