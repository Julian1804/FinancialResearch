import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from pypdf import PdfReader
import fitz
import pdfplumber

from config.settings import PARSE_ENABLE_MULTIMODAL, PARSE_IMAGE_SCALE, PARSE_MAX_MULTIMODAL_PAGES, PARSE_TEXT_RESCUE_PAGE_LIMIT
from services.vision_parser_service import parse_page_with_multimodal
from services.period_service import build_period_metadata
from utils.file_utils import build_page_images_folder

ProgressCallback = Optional[Callable[[int, int, str], None]]


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\x00", " ")
    text = text.replace("\ufeff", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def calc_text_quality_score(text: str) -> float:
    if not text:
        return 0.0
    text_len = len(text)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[A-Za-z]", text))
    digits = len(re.findall(r"\d", text))
    weird_chars = len(re.findall(r"[�□■◆◇¤�]", text))
    printable_ratio = (chinese_chars + english_chars + digits) / max(text_len, 1)
    score = 0.0
    score += min(text_len, 4000) / 80
    score += printable_ratio * 60
    score -= weird_chars * 4
    return score


def detect_language(text: str) -> str:
    if not text or len(text.strip()) < 20:
        return "unknown"
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_count = len(re.findall(r"[A-Za-z]", text))
    trad_markers = len(re.findall(r"[國報業務關聯會計應收資產負債權益營運風險醫療藥務經營審核證券銷售增長發展數據網絡競爭優勢現金損益說明]", text))
    simp_markers = len(re.findall(r"[国报业务关联会计应收资产负债权益营运风险医疗药务经营审核证券销售增长发展数据网络竞争优势现金损益说明]", text))
    if chinese_count > 30 and english_count > 30:
        if trad_markers > simp_markers:
            return "mixed_zh_tw"
        if simp_markers > trad_markers:
            return "mixed_zh_cn"
        return "mixed"
    if english_count > chinese_count * 1.5 and english_count > 80:
        return "en"
    if chinese_count > 30:
        if trad_markers > simp_markers:
            return "zh_tw"
        if simp_markers > trad_markers:
            return "zh_cn"
        return "zh"
    return "unknown"


def classify_page_type(text: str) -> str:
    if not text or len(text.strip()) < 30:
        return "scanned_or_image"
    text_len = len(text)
    line_count = max(len(text.splitlines()), 1)
    digits = len(re.findall(r"\d", text))
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_chars = len(re.findall(r"[A-Za-z]", text))
    weird_chars = len(re.findall(r"[�□■◆◇¤�]", text))
    percent_count = text.count("%")
    currency_count = len(re.findall(r"[¥￥$€港元人民币人民幣元亿元萬元万亿]", text))
    table_like_separators = len(re.findall(r"[\t|]{1,}", text))
    avg_line_len = text_len / line_count
    readable_ratio = (digits + chinese_chars + english_chars) / max(text_len, 1)
    if digits > 40 and (percent_count > 3 or currency_count > 3 or table_like_separators > 2):
        return "table_like"
    if weird_chars > 5 or readable_ratio < 0.35:
        return "text_bad"
    if digits > 20 and avg_line_len < 25:
        return "mixed_layout"
    return "text_good"


def _extract_text_with_pymupdf_doc(doc) -> list[str]:
    pages = []
    for page in doc:
        try:
            text = page.get_text("text")
        except Exception:
            text = ""
        pages.append(normalize_text(text))
    return pages


def _extract_page_text_with_pdfplumber(file_path: str, page_number_1based: int) -> str:
    try:
        with pdfplumber.open(file_path) as pdf:
            if 0 <= page_number_1based - 1 < len(pdf.pages):
                return normalize_text(pdf.pages[page_number_1based - 1].extract_text() or "")
    except Exception:
        return ""
    return ""


def _extract_page_text_with_pypdf(file_path: str, page_number_1based: int) -> str:
    try:
        reader = PdfReader(file_path)
        if 0 <= page_number_1based - 1 < len(reader.pages):
            return normalize_text(reader.pages[page_number_1based - 1].extract_text() or "")
    except Exception:
        return ""
    return ""


def _choose_best_page_text(page_text_candidates: dict) -> tuple[str, str, dict]:
    scored = {engine_name: calc_text_quality_score(text) for engine_name, text in page_text_candidates.items()}
    best_engine = max(scored, key=scored.get)
    best_text = page_text_candidates[best_engine]
    return best_engine, best_text, scored


def _parse_page_with_text_engine(best_text: str, language: str, engine_name: str) -> dict:
    return {
        "engine": engine_name,
        "text": best_text,
        "language": language,
        "raw_markdown": "",
        "table_blocks": [],
        "image_blocks": [],
        "notes": "当前页使用传统文本提取引擎。",
    }


def _render_page_to_image(doc, file_path: str, page_index: int) -> str:
    output_folder = build_page_images_folder(file_path)
    image_path = os.path.join(output_folder, f"page_{page_index + 1:03d}.png")
    if not os.path.exists(image_path):
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(PARSE_IMAGE_SCALE, PARSE_IMAGE_SCALE))
        pix.save(image_path)
    return image_path


def _needs_text_rescue(page_type: str, score_map: dict, best_engine: str) -> bool:
    best_score = score_map.get(best_engine, 0)
    if page_type in {"scanned_or_image", "text_bad", "mixed_layout", "table_like"}:
        return True
    return best_score < 18


def _route_page_parser(*, doc, file_path: str, page_index: int, page_type: str, best_text: str, language: str, best_engine: str, allow_multimodal: bool) -> dict:
    if page_type == "text_good" or not allow_multimodal:
        return _parse_page_with_text_engine(best_text=best_text, language=language, engine_name=best_engine)

    image_path = _render_page_to_image(doc, file_path, page_index)
    mm_result = parse_page_with_multimodal(
        image_path=image_path,
        fallback_text=best_text,
        page_number=page_index + 1,
    )
    return {
        "engine": mm_result["engine"],
        "text": mm_result["text"],
        "language": language,
        "raw_markdown": mm_result.get("raw_markdown", ""),
        "table_blocks": mm_result.get("table_blocks", []),
        "image_blocks": mm_result.get("image_blocks", []),
        "notes": mm_result.get("notes", ""),
    }


def extract_best_text_from_pdf(file_path: str, progress_callback: ProgressCallback = None) -> dict:
    doc = fitz.open(file_path)
    pymupdf_pages = _extract_text_with_pymupdf_doc(doc)
    page_count = len(pymupdf_pages)
    pages_data = []
    full_text_parts = []
    engine_counter = Counter()
    page_type_counter = Counter()

    initial_candidates = []
    rescue_indexes = []

    total_progress_steps = max(1, page_count + min(page_count, PARSE_TEXT_RESCUE_PAGE_LIMIT) + min(page_count, PARSE_MAX_MULTIMODAL_PAGES) + 2)
    progress_done = 0

    for i, base_text in enumerate(pymupdf_pages):
        score_map = {"pymupdf": calc_text_quality_score(base_text)}
        page_type = classify_page_type(base_text)
        page_language = detect_language(base_text)
        initial_candidates.append({
            "pymupdf": base_text,
            "score_map": score_map,
            "best_engine": "pymupdf",
            "best_text": base_text,
            "page_type": page_type,
            "language": page_language,
        })
        if _needs_text_rescue(page_type, score_map, "pymupdf"):
            rescue_indexes.append(i)
        progress_done += 1
        if progress_callback:
            progress_callback(progress_done, total_progress_steps, f"快速扫描页面 {i + 1}/{page_count}")

    rescue_indexes = rescue_indexes[:PARSE_TEXT_RESCUE_PAGE_LIMIT]
    for idx in rescue_indexes:
        page_no = idx + 1
        candidates = {"pymupdf": initial_candidates[idx]["pymupdf"]}
        pdfplumber_text = _extract_page_text_with_pdfplumber(file_path, page_no)
        if pdfplumber_text:
            candidates["pdfplumber"] = pdfplumber_text
        pypdf_text = _extract_page_text_with_pypdf(file_path, page_no)
        if pypdf_text:
            candidates["pypdf"] = pypdf_text
        best_engine, best_text, score_map = _choose_best_page_text(candidates)
        initial_candidates[idx].update({
            "score_map": score_map,
            "best_engine": best_engine,
            "best_text": best_text,
            "page_type": classify_page_type(best_text),
            "language": detect_language(best_text),
            **candidates,
        })
        progress_done += 1
        if progress_callback:
            progress_callback(progress_done, total_progress_steps, f"文本补救页面 {page_no}/{page_count}")

    multimodal_candidates = []
    for idx, item in enumerate(initial_candidates):
        if item["page_type"] in {"scanned_or_image", "text_bad", "mixed_layout", "table_like"}:
            multimodal_candidates.append((idx, item))
    multimodal_candidates.sort(key=lambda x: x[1]["score_map"].get(x[1]["best_engine"], 0))
    multimodal_indexes = {idx for idx, _ in multimodal_candidates[:PARSE_MAX_MULTIMODAL_PAGES]}

    for i, item in enumerate(initial_candidates):
        allow_multimodal = PARSE_ENABLE_MULTIMODAL and i in multimodal_indexes
        parsed_page = _route_page_parser(
            doc=doc,
            file_path=file_path,
            page_index=i,
            page_type=item["page_type"],
            best_text=item["best_text"],
            language=item["language"],
            best_engine=item["best_engine"],
            allow_multimodal=allow_multimodal,
        )
        engine_counter[parsed_page["engine"]] += 1
        page_type_counter[item["page_type"]] += 1
        image_path = _render_page_to_image(doc, file_path, i) if allow_multimodal else ""
        page_record = {
            "page_number": i + 1,
            "page_image_path": image_path,
            "page_type": item["page_type"],
            "language": parsed_page["language"],
            "engine": parsed_page["engine"],
            "scores": item["score_map"],
            "text": parsed_page["text"],
            "raw_markdown": parsed_page["raw_markdown"],
            "table_blocks": parsed_page["table_blocks"],
            "image_blocks": parsed_page["image_blocks"],
            "notes": parsed_page["notes"],
        }
        pages_data.append(page_record)
        if parsed_page["text"]:
            full_text_parts.append(parsed_page["text"])
        progress_done += 1
        if progress_callback:
            progress_callback(progress_done, total_progress_steps, f"整合页面 {i + 1}/{page_count}")

    doc.close()
    full_text = "\n\n".join(full_text_parts)
    dominant_language = detect_language(full_text)
    return {
        "page_count": page_count,
        "full_text": full_text,
        "pages": pages_data,
        "engine_summary": dict(engine_counter),
        "page_type_summary": dict(page_type_counter),
        "dominant_language": dominant_language,
        "parse_strategy_summary": {
            "quick_engine": "pymupdf",
            "rescued_page_count": len(rescue_indexes),
            "multimodal_page_count": len(multimodal_indexes),
            "multimodal_enabled": PARSE_ENABLE_MULTIMODAL,
            "multimodal_page_cap": PARSE_MAX_MULTIMODAL_PAGES,
            "text_rescue_page_cap": PARSE_TEXT_RESCUE_PAGE_LIMIT,
        },
    }


def build_parsed_output(company_name: str, file_path: str, progress_callback: ProgressCallback = None) -> dict:
    parsed_result = extract_best_text_from_pdf(file_path, progress_callback=progress_callback)
    source_file = os.path.basename(file_path)
    full_text = parsed_result["full_text"]
    period_meta = build_period_metadata(source_file=source_file, text=full_text)
    if progress_callback:
        progress_callback(parsed_result.get("page_count", 0) + 999, parsed_result.get("page_count", 0) + 1000, "抽取期间与材料元数据")
    return {
        "company_name": company_name,
        "source_file": source_file,
        "file_path": file_path,
        "page_count": parsed_result["page_count"],
        "dominant_language": parsed_result["dominant_language"],
        "engine_summary": parsed_result["engine_summary"],
        "page_type_summary": parsed_result["page_type_summary"],
        "parse_strategy_summary": parsed_result.get("parse_strategy_summary", {}),
        "full_text": full_text,
        "pages": parsed_result["pages"],
        **period_meta,
    }


def save_parsed_json(parsed_data: dict, output_path: str) -> None:
    import json
    from pathlib import Path
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed_data, f, ensure_ascii=False, indent=2)
