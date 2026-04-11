from services.provider_service import call_agent_chat
from services.research_utils import safe_json_loads, truncate_text


def build_json_repair_prompt(expected_top_keys: list[str] | None = None) -> str:
    keys_text = f"期望顶层键：{expected_top_keys}" if expected_top_keys else ""
    return f"""
你是 JSON 修复助手。你会收到一段接近 JSON 但格式损坏的文本。
要求：
1. 只输出修复后的纯 JSON，不要解释，不要 Markdown。
2. 尽量保留原始字段和值，不要擅自删改业务含义。
3. 如某字段明显断裂，可尽量闭合结构，但不要凭空扩写业务内容。
4. 保证双引号、逗号、括号、数组都合法。
5. {keys_text}
""".strip()


def repair_json_payload(raw_text: str, expected_top_keys: list[str] | None = None) -> dict:
    repaired = call_agent_chat("json_repair_agent", build_json_repair_prompt(expected_top_keys), truncate_text(raw_text, 22000))
    payload = safe_json_loads(repaired)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 修复后顶层不是对象，而是：{type(payload).__name__}")
    return payload
