import sys
from pathlib import Path

import streamlit as st

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from services.company_ui_service import format_company_option, get_company_folder_path, get_company_select_values
from services.repository_service import refresh_company_repository
from services.retrieval_service import answer_company_question, build_company_retrieval_index


def qa_page():
    st.title("问答检索（本地混合检索 + AI 回答）")

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

    if st.button("刷新公司索引并重建问答索引"):
        refresh_company_repository(get_company_folder_path(selected_company))
        payload = build_company_retrieval_index(get_company_folder_path(selected_company), force_rebuild=True)
        st.success(f"问答索引已重建，chunk 数量：{payload.get('chunk_count', 0)}")

    question = st.text_area("请输入问题", placeholder="例如：药明生物 2026FY 的主要风险是什么？上一版预期和现在相比改了什么？")
    top_k = st.slider("召回 top_k", min_value=3, max_value=15, value=8)

    if st.button("开始检索并回答"):
        if not question.strip():
            st.error("请先输入问题。")
            return

        with st.spinner("正在检索并组织答案..."):
            result = answer_company_question(selected_company, question.strip(), top_k=top_k)

        st.subheader("回答")
        st.write(result.get("answer", "资料不足"))

        st.subheader("引用来源")
        for idx, item in enumerate(result.get("citations", []), start=1):
            st.markdown(
                f"**[{idx}]** {item.get('title', '')} ｜ period_key=`{item.get('period_key', '')}` ｜ source_type=`{item.get('source_type', '')}` ｜ score=`{item.get('score', 0)}`"
            )

        with st.expander("检索结果明细"):
            st.json(result.get("retrieval", {}))


if __name__ == "__main__":
    qa_page()