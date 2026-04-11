import os
from pathlib import Path
from difflib import get_close_matches
import streamlit as st
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from utils.file_utils import ensure_company_structure, list_company_folders
from services.repository_service import refresh_company_repository


def get_unique_file_path(folder_path, original_filename):
    base_name, ext = os.path.splitext(original_filename)
    candidate_path = os.path.join(folder_path, original_filename)
    counter = 1
    while os.path.exists(candidate_path):
        new_filename = f"{base_name}_{counter}{ext}"
        candidate_path = os.path.join(folder_path, new_filename)
        counter += 1
    return candidate_path


def find_similar_companies(company_name, max_results=5):
    all_companies = list_company_folders()
    contains_matches = [name for name in all_companies if company_name.lower() in name.lower() or name.lower() in company_name.lower()]
    fuzzy_matches = get_close_matches(company_name, all_companies, n=max_results, cutoff=0.4)
    combined = []
    for name in contains_matches + fuzzy_matches:
        if name not in combined:
            combined.append(name)
    return combined[:max_results]


def save_uploaded_file(target_company_folder, uploaded_file):
    reports_folder = Path(target_company_folder) / "年报"
    reports_folder.mkdir(parents=True, exist_ok=True)
    file_path = get_unique_file_path(str(reports_folder), uploaded_file.name)
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    refresh_company_repository(target_company_folder)

    saved_filename = os.path.basename(file_path)
    st.success(f"文件《{uploaded_file.name}》已成功上传。")
    st.write(f"保存目录：{reports_folder}")
    st.write(f"实际保存文件名：{saved_filename}")
    st.write(f"完整路径：{file_path}")

    with open(file_path, "rb") as f:
        st.download_button("下载该文件", data=f.read(), file_name=saved_filename, mime="application/pdf")


def upload_file():
    st.title("上传财报 / 辅助材料")
    company_name = st.text_input("请输入公司名称")
    uploaded_file = st.file_uploader("选择 PDF 文件", type=["pdf"])

    if uploaded_file is not None:
        company_name = company_name.strip()
        if not company_name:
            st.error("无法上传：请先输入公司名称。")
            return

        similar_companies = find_similar_companies(company_name)
        if similar_companies:
            st.warning("检测到以下相似公司文件夹，请确认保存位置：")
            options = similar_companies + [f"新建文件夹：{company_name}"]
            selected_option = st.radio("请选择保存位置：", options=options, index=0)
            if st.button("确认并上传"):
                target_name = company_name if selected_option.startswith("新建文件夹：") else selected_option
                target_company_folder = ensure_company_structure(target_name)
                save_uploaded_file(target_company_folder, uploaded_file)
        else:
            st.info(f"未找到相似公司文件夹，将新建：{company_name}")
            if st.button("确认并上传"):
                target_company_folder = ensure_company_structure(company_name)
                save_uploaded_file(target_company_folder, uploaded_file)


if __name__ == "__main__":
    upload_file()
