from pathlib import Path

from services.llm_gateway_service import call_profile_vision
from services.research_utils import safe_json_loads

VISION_PARSE_PROMPT = """
你是一名财报文档复杂页面解析助手。
输入是一张 PDF 页面图片。请专门处理这些传统文本引擎容易失真的页面：
- 图表 + 文字混排
- 扫描页
- 表格页
- 图片型公告页

请只返回 JSON：
{
  "ocr_text": "尽量还原页面正文与表格中的关键信息",
  "table_markdown": "如果存在表格，用 markdown 表格或表格式文本返回；否则为空字符串",
  "page_summary": "一句话概括这页主要内容",
  "key_figures": ["提取出的关键数值或关键字段"],
  "image_or_chart_notes": ["图表/图片说明"],
  "confidence": "high/medium/low"
}

要求：
1. 不能编造。
2. 看不清就保守写“信息不足”。
3. 优先保留数字、单位、同比/环比、表头、日期。
4. 输出必须是纯 JSON。
""".strip()


def parse_page_with_multimodal(image_path: str, fallback_text: str = "", page_number: int = 0, profile_name: str = "aliyun_vision_free") -> dict:
    filename = Path(image_path).name if image_path else ""
    try:
        raw = call_profile_vision(profile_name=profile_name, prompt=VISION_PARSE_PROMPT, image_path=image_path)
        payload = safe_json_loads(raw)
        ocr_text = (payload.get("ocr_text") or "").strip()
        table_markdown = (payload.get("table_markdown") or "").strip()
        summary = (payload.get("page_summary") or "").strip()

        merged_parts = [part for part in [ocr_text, table_markdown] if part]
        if not merged_parts and fallback_text:
            merged_parts.append(fallback_text)
        merged_text = "\n\n".join(merged_parts).strip()

        return {
            "engine": "aliyun_multimodal",
            "text": merged_text or fallback_text or f"[复杂页解析为空] 第 {page_number} 页：{filename}",
            "raw_markdown": table_markdown,
            "table_blocks": [table_markdown] if table_markdown else [],
            "image_blocks": payload.get("image_or_chart_notes", []) or [],
            "notes": f"多模态解析成功：{summary or '无摘要'}",
            "vision_payload": payload,
        }
    except Exception as exc:
        if fallback_text and len(fallback_text.strip()) > 20:
            extracted_text = fallback_text
        else:
            extracted_text = f"[多模态解析失败回退] 第 {page_number} 页当前被判定为复杂页面，已保留页面图片：{filename}。失败原因：{exc}"

        return {
            "engine": "multimodal_fallback",
            "text": extracted_text,
            "raw_markdown": "",
            "table_blocks": [],
            "image_blocks": [],
            "notes": f"多模态解析失败，已回退到传统文本：{exc}",
            "vision_payload": {},
        }
