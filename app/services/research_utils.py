import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

import json5


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_whitespace(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate_text(text: str, limit: int) -> str:
    text = normalize_whitespace(text)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[截断]"


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 120) -> List[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_outer_json_candidate(text: str) -> str:
    text = _strip_code_fences(text)
    stack = []
    start_idx = None
    best = ""
    for idx, ch in enumerate(text):
        if ch in "[{":
            if start_idx is None:
                start_idx = idx
            stack.append(ch)
        elif ch in "]}":
            if not stack:
                continue
            opener = stack[-1]
            if (opener == "{" and ch == "}") or (opener == "[" and ch == "]"):
                stack.pop()
                if not stack and start_idx is not None:
                    best = text[start_idx:idx + 1]
    if best:
        return best.strip()
    return text.strip()


def _clean_common_json_issues(text: str) -> str:
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("，", ",").replace("：", ":") if text.strip().startswith("{") or text.strip().startswith("[") else text
    text = re.sub(r",(\s*[}\]])", r"", text)
    return text.strip()


def safe_json_loads(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("模型返回为空，无法解析 JSON。")

    cleaned = _clean_common_json_issues(_extract_outer_json_candidate(text))

    last_error = None
    for loader in (json.loads, json5.loads):
        try:
            payload = loader(cleaned)
            if isinstance(payload, str):
                nested = _clean_common_json_issues(_extract_outer_json_candidate(payload))
                try:
                    payload = loader(nested)
                except Exception:
                    pass
            return payload
        except Exception as exc:
            last_error = exc
            continue

    preview = truncate_text(cleaned, 1200)
    raise ValueError(f"模型返回的 JSON 无法解析：{last_error}。原始片段：\n{preview}")


def compact_json_text(data: Any, max_chars: int = 3000) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        text = str(data)
    return truncate_text(text, max_chars)


FINANCIAL_METRIC_KEYWORDS = {
    "revenue": ["营业收入", "收入", "收益", "revenue", "turnover", "sales"],
    "gross_profit": ["毛利", "gross profit"],
    "gross_margin": ["毛利率", "gross margin"],
    "net_profit": ["净利润", "归母净利润", "profit attributable", "net profit", "profit"],
    "operating_cash_flow": ["经营活动现金流", "经营现金流", "operating cash flow"],
    "cash": ["现金及现金等价物", "cash and cash equivalents", "cash"],
    "debt": ["有息负债", "借款", "debt", "borrowings", "bank loans"],
    "inventory": ["存货", "inventory"],
    "capex": ["资本开支", "capital expenditure", "capex"],
    "rd": ["研发费用", "research and development", "r&d"],
    "order_backlog": ["在手订单", "backlog", "order backlog", "new bookings"],
    "utilization": ["产能利用率", "稼动率", "utilization"],
}


def _extract_numeric_tokens(text: str) -> List[str]:
    tokens = re.findall(
        r"(?:同比|环比|增长|下降|increase|decrease|up|down)?\s*[-+]?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|pct|个百分点|bps|亿元|万元|百万元|千元|million|billion|bn|m)?",
        text,
        flags=re.IGNORECASE,
    )
    uniq = []
    for token in tokens:
        token = token.strip()
        if token and token not in uniq:
            uniq.append(token)
    return uniq[:8]


def extract_metric_candidates(full_text: str, limit_per_metric: int = 5) -> List[Dict[str, Any]]:
    full_text = normalize_whitespace(full_text)
    if not full_text:
        return []

    raw_lines = []
    for block in re.split(r"\n+", full_text[:120000]):
        line = normalize_whitespace(block)
        if len(line) < 6:
            continue
        raw_lines.append(line)

    results = []
    for metric_key, keywords in FINANCIAL_METRIC_KEYWORDS.items():
        seen = []
        for line in raw_lines:
            lowered = line.lower()
            if any(keyword.lower() in lowered for keyword in keywords):
                item = {
                    "metric_key": metric_key,
                    "keywords": keywords,
                    "snippet": truncate_text(line, 220),
                    "numeric_tokens": _extract_numeric_tokens(line),
                }
                if item["snippet"] not in seen:
                    seen.append(item["snippet"])
                    results.append(item)
                if len(seen) >= limit_per_metric:
                    break
    return results


def deduplicate_dict_items(items: Iterable[Dict[str, Any]], unique_key: str) -> List[Dict[str, Any]]:
    seen = set()
    output = []
    for item in items:
        value = item.get(unique_key)
        if value in seen:
            continue
        seen.add(value)
        output.append(item)
    return output


def ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
