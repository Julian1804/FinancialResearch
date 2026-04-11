from pathlib import Path
from typing import Dict, List

from config.settings import DATA_DIR
from services.provider_service import call_agent_chat
from services.repository_service import refresh_company_repository
from services.sqlite_index_service import search_company_chunks
from utils.file_utils import build_qa_chunks_path, load_json_file, save_json_file


def _llm_answer(system_prompt: str, user_prompt: str) -> str:
    try:
        return call_agent_chat("qa_agent", system_prompt, user_prompt)
    except Exception:
        return ""


def build_company_retrieval_index(company_folder: str | Path, force_rebuild: bool = False) -> Dict:
    company_folder = Path(company_folder)
    qa_chunks_path = Path(build_qa_chunks_path(company_folder))

    if qa_chunks_path.exists() and not force_rebuild:
        try:
            return load_json_file(qa_chunks_path)
        except Exception:
            pass

    refreshed = refresh_company_repository(company_folder)

    if qa_chunks_path.exists():
        try:
            return load_json_file(qa_chunks_path)
        except Exception:
            pass

    fallback = {"company_name": company_folder.name, "chunk_count": 0, "chunks": [], "summary": refreshed.get("summary", {})}
    save_json_file(fallback, qa_chunks_path)
    return fallback


def _build_context_blocks(retrieved: List[Dict]) -> str:
    blocks = []
    for idx, item in enumerate(retrieved, start=1):
        blocks.append(
            f"[资料{idx}]\n"
            f"title: {item.get('title', '')}\n"
            f"period_key: {item.get('period_key', '')}\n"
            f"source_type: {item.get('source_type', '')}\n"
            f"document_type: {item.get('document_type', '')}\n"
            f"score: {item.get('score', 0)}\n"
            f"text:\n{item.get('chunk_text', '')}\n"
        )
    return "\n".join(blocks)


def _fallback_answer(question: str, retrieved: List[Dict]) -> str:
    if not retrieved:
        return "资料不足，当前没有检索到可支持回答的材料。"

    lines = ["当前先给你一个基于已召回材料的保守回答：", f"问题：{question}", "", "高相关资料摘要："]
    for idx, item in enumerate(retrieved[:5], start=1):
        text = (item.get("chunk_text", "") or "").strip().replace("\n", " ")
        lines.append(f"{idx}. {item.get('title', '')} ｜ period_key={item.get('period_key', '')} ｜ source_type={item.get('source_type', '')} ｜ {text[:220]}")
    lines.append("")
    lines.append("说明：当前回答为检索兜底版，尚未调用大模型总结。")
    return "\n".join(lines)


def answer_company_question(company_name: str, question: str, top_k: int = 8) -> Dict:
    company_folder = Path(DATA_DIR) / company_name
    build_company_retrieval_index(company_folder, force_rebuild=False)
    retrieved = search_company_chunks(company_name, question, top_k=top_k)

    citations = [{"title": item.get("title", ""), "period_key": item.get("period_key", ""), "source_type": item.get("source_type", ""), "score": item.get("score", 0)} for item in retrieved]

    if not retrieved:
        return {"answer": "资料不足，当前没有检索到支持回答的材料。", "citations": [], "retrieval": {"question": question, "top_k": top_k, "hits": []}}

    system_prompt = "你是财报研究问答助手。只能根据给定资料回答；资料不足就明确说资料不足；不要编造；不要使用未来信息。"
    user_prompt = f"用户问题：\n{question}\n\n已召回资料如下：\n{_build_context_blocks(retrieved)}\n\n请输出简洁中文回答。"
    llm_text = _llm_answer(system_prompt, user_prompt)
    answer = llm_text.strip() if llm_text.strip() else _fallback_answer(question, retrieved)

    return {"answer": answer, "citations": citations, "retrieval": {"question": question, "top_k": top_k, "hits": retrieved}}
