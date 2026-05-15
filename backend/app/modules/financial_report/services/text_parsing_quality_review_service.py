from __future__ import annotations

import hashlib
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.services.canonical_financial_fact_extraction_service import (
    load_trusted_canonical_facts_for_analysis,
)
from backend.app.modules.financial_report.services.parse_lab_field_candidate_ingestion_service import (
    DEFAULT_PARSE_LAB_EXPORT_DIR,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
PARSE_LAB_RUNTIME_DIR = Path(r"D:\workspace\runtime\parse_lab")
TEXT_QUALITY_REVIEW_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "text_quality_review_pack"
)

RISK_LABELS = [
    "numeric_parse_risk",
    "unit_currency_risk",
    "period_risk",
    "growth_direction_risk",
    "negative_or_condition_missing_risk",
    "sentence_boundary_risk",
    "mixed_language_risk",
    "sentiment_or_strategy_summary_risk",
    "missing_context_risk",
    "hallucinated_summary_risk",
    "low_risk",
]

FINANCIAL_NUMERIC_KEYWORDS = (
    "revenue",
    "income",
    "profit",
    "gross",
    "margin",
    "expense",
    "cost",
    "cash flow",
    "assets",
    "liabilities",
    "equity",
    "收入",
    "收益",
    "利润",
    "利潤",
    "毛利",
    "费用",
    "費用",
    "成本",
    "现金流",
    "現金流",
    "资产",
    "資產",
    "负债",
    "負債",
    "权益",
    "權益",
)
EXPLANATION_KEYWORDS = (
    "because",
    "primarily",
    "mainly",
    "due to",
    "as a result",
    "原因",
    "主要",
    "由于",
    "由於",
    "得益于",
    "导致",
    "帶動",
    "推动",
)
SENTIMENT_STRATEGY_KEYWORDS = (
    "management",
    "strategy",
    "strategic",
    "outlook",
    "market",
    "risk",
    "uncertainty",
    "plan",
    "expect",
    "管理层",
    "管理層",
    "战略",
    "戰略",
    "策略",
    "展望",
    "市场",
    "市場",
    "风险",
    "風險",
    "不确定",
    "不確定",
    "计划",
    "計劃",
    "预计",
    "預計",
)
UNCERTAINTY_OR_CONDITION_KEYWORDS = (
    "may",
    "might",
    "could",
    "if",
    "subject to",
    "depending",
    "unless",
    "可能",
    "预计",
    "預計",
    "计划",
    "計劃",
    "力争",
    "視情況",
    "视情况",
    "若",
    "如",
    "倘",
)
NEGATIVE_KEYWORDS = (
    "not",
    "no ",
    "without",
    "decrease",
    "decline",
    "down",
    "loss",
    "不得",
    "未",
    "沒有",
    "没有",
    "下降",
    "减少",
    "減少",
    "亏损",
    "虧損",
)


def generate_text_parsing_quality_review_pack(
    output_dir: Path | str = TEXT_QUALITY_REVIEW_OUTPUT_DIR,
    target_count: int = 220,
    review_queue_count: int = 100,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = _collect_text_candidates()
    samples = _select_samples(candidates, target_count)
    machine_precheck = [_build_precheck(sample, index) for index, sample in enumerate(samples, start=1)]
    review_queue = _build_human_review_queue(machine_precheck, review_queue_count)
    summary = _build_summary(output_dir, machine_precheck, review_queue, len(candidates))
    _write_outputs(output_dir, machine_precheck, review_queue, summary)
    return {
        "summary": summary,
        "machine_precheck": machine_precheck,
        "review_queue": review_queue,
    }


def _collect_text_candidates() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    candidates.extend(_field_candidate_texts())
    candidates.extend(_review_queue_texts())
    candidates.extend(_parse_qa_issue_texts())
    candidates.extend(_pages_jsonl_texts())
    return _dedupe_candidates(candidates)


def _field_candidate_texts() -> list[dict[str, Any]]:
    path = DEFAULT_PARSE_LAB_EXPORT_DIR / "financialresearch_field_candidates.json"
    payload = _read_json(path, {"items": []})
    rows = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in payload.get("items", []):
        text = str(row.get("evidence_text") or "").strip()
        key = (str(row.get("source_pdf") or ""), str(row.get("evidence_id") or ""), int(row.get("source_page") or 0), text[:80])
        if not text or key in seen:
            continue
        seen.add(key)
        rows.append(
            _candidate(
                text=text,
                parsed_text=_clean_text(text),
                source_pdf=str(row.get("source_pdf") or ""),
                source_page=int(row.get("source_page") or 0),
                source_kind="round3_field_candidate_evidence",
                source_ref=str(row.get("field_candidate_id") or row.get("evidence_id") or ""),
            )
        )
    return rows


def _review_queue_texts() -> list[dict[str, Any]]:
    path = DEFAULT_PARSE_LAB_EXPORT_DIR / "financialresearch_review_queue.json"
    payload = _read_json(path, {"items": []})
    rows = []
    seen: set[tuple[str, str, int, str]] = set()
    for row in payload.get("items", []):
        text = str(row.get("evidence_text") or "").strip()
        key = (str(row.get("source_pdf") or ""), str(row.get("review_item_id") or ""), int(row.get("source_page") or 0), text[:80])
        if not text or key in seen:
            continue
        seen.add(key)
        rows.append(
            _candidate(
                text=text,
                parsed_text=_clean_text(text),
                source_pdf=str(row.get("source_pdf") or ""),
                source_page=int(row.get("source_page") or 0),
                source_kind="round3_review_queue_text",
                source_ref=str(row.get("review_item_id") or ""),
            )
        )
    return rows


def _parse_qa_issue_texts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in [PARSE_LAB_RUNTIME_DIR / "parse_qa" / "auto_check_results.jsonl", PARSE_LAB_RUNTIME_DIR / "parse_qa" / "issues.jsonl"]:
        if not path.exists():
            continue
        for item in _read_jsonl(path):
            issues = item.get("auto_issues") if isinstance(item.get("auto_issues"), list) else [item]
            for issue in issues:
                text = str(issue.get("raw_text_excerpt") or issue.get("note") or "").strip()
                if len(text) < 40:
                    continue
                rows.append(
                    _candidate(
                        text=text,
                        parsed_text=_clean_text(text),
                        source_pdf=str(issue.get("pdf_name") or item.get("pdf_name") or ""),
                        source_page=int(issue.get("page_number") or item.get("page_number") or 0),
                        source_kind="parse_qa_issue_excerpt",
                        source_ref=str(issue.get("issue_id") or item.get("task_id") or path.name),
                    )
                )
    return rows


def _pages_jsonl_texts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    pages_paths = sorted((PARSE_LAB_RUNTIME_DIR / "results").rglob("*.pages.jsonl"))
    pages_paths.extend(sorted((PARSE_LAB_RUNTIME_DIR / "results" / "api_v1").rglob("pages.jsonl")))
    for path in pages_paths[:30]:
        for page in _read_jsonl(path):
            text = str(page.get("final_text") or page.get("primary_text") or "").strip()
            if len(text) < 80:
                continue
            for chunk_index, chunk in enumerate(_chunk_text(text), start=1):
                rows.append(
                    _candidate(
                        text=chunk,
                        parsed_text=_clean_text(chunk),
                        source_pdf=str(page.get("pdf_name") or path.parent.name),
                        source_page=int(page.get("page_number") or 0),
                        source_kind="parse_result_page_text",
                        source_ref=f"{path.name}::chunk_{chunk_index}",
                    )
                )
    return rows


def _candidate(text: str, parsed_text: str, source_pdf: str, source_page: int, source_kind: str, source_ref: str) -> dict[str, Any]:
    categories = _classify_categories(parsed_text)
    return {
        "raw_text": text,
        "parsed_text": parsed_text,
        "source_pdf": source_pdf,
        "source_page": source_page,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "categories": categories,
        "risk_seed": _risk_seed(parsed_text),
    }


def _select_samples(candidates: list[dict[str, Any]], target_count: int) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        for category in candidate["categories"]:
            buckets[category].append(candidate)
    quotas = {
        "financial_numeric": 90,
        "financial_explanation": 45,
        "sentiment_strategy": 35,
        "complex_language": 40,
        "low_risk": 10,
    }
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for category, quota in quotas.items():
        for candidate in sorted(buckets.get(category, []), key=lambda row: row["risk_seed"], reverse=True):
            key = _fingerprint(candidate["parsed_text"])
            if key in seen:
                continue
            selected.append(candidate)
            seen.add(key)
            if sum(1 for row in selected if category in row["categories"]) >= quota:
                break
    for candidate in sorted(candidates, key=lambda row: row["risk_seed"], reverse=True):
        if len(selected) >= target_count:
            break
        key = _fingerprint(candidate["parsed_text"])
        if key not in seen:
            selected.append(candidate)
            seen.add(key)
    return selected[:target_count]


def _build_precheck(sample: dict[str, Any], index: int) -> dict[str, Any]:
    parsed_text = sample["parsed_text"]
    risk_labels = _risk_labels(parsed_text, sample["categories"])
    risk_score = _risk_score(risk_labels, parsed_text)
    trusted_candidate = _trusted_by_text_candidate(risk_labels, sample["categories"])
    return {
        "sample_id": f"text_quality_{index:04d}",
        "source_pdf": sample["source_pdf"],
        "source_page": sample["source_page"],
        "source_kind": sample["source_kind"],
        "source_ref": sample["source_ref"],
        "categories": sample["categories"],
        "raw_text": sample["raw_text"],
        "parsed_text": parsed_text,
        "ai_summary": _one_sentence_summary(parsed_text, sample["categories"]),
        "ai_precheck": {
            "parsed_text_complete": not _has_missing_context_risk(parsed_text),
            "ocr_linebreak_sentence_issue": _has_sentence_boundary_risk(parsed_text),
            "numeric_identification_ok": not ("numeric_parse_risk" in risk_labels),
            "unit_currency_identification_ok": not ("unit_currency_risk" in risk_labels),
            "period_identification_ok": not ("period_risk" in risk_labels),
            "growth_direction_identification_ok": not ("growth_direction_risk" in risk_labels),
            "negative_or_condition_preserved": not ("negative_or_condition_missing_risk" in risk_labels),
            "trusted_by_text_candidate": trusted_candidate,
            "trusted_by_text_decision": "needs_human_review" if not trusted_candidate else "candidate_after_human_confirmation",
            "risk_labels": risk_labels,
            "risk_score": risk_score,
        },
        "review_priority": "high" if risk_score >= 5 else "medium" if risk_score >= 3 else "low",
        "human_review_fields": _human_review_fields(),
    }


def _build_human_review_queue(machine_precheck: list[dict[str, Any]], review_queue_count: int) -> list[dict[str, Any]]:
    sorted_samples = sorted(machine_precheck, key=lambda row: row["ai_precheck"]["risk_score"], reverse=True)
    return [
        {
            "sample_id": row["sample_id"],
            "review_priority": row["review_priority"],
            "source_pdf": row["source_pdf"],
            "source_page": row["source_page"],
            "ai_precheck_snapshot": row["ai_precheck"],
            "human_review": _human_review_fields(),
            "ai_human_disagreement_fields": {
                "numeric_error_missed": None,
                "unit_currency_error_missed": None,
                "period_error_missed": None,
                "summary_over_interpreted": None,
                "summary_hallucinated": None,
                "false_high_risk": None,
                "false_low_risk": None,
            },
        }
        for row in sorted_samples[:review_queue_count]
    ]


def _human_review_fields() -> dict[str, Any]:
    return {
        "original_text_complete": None,
        "numbers_correct": None,
        "unit_currency_percent_correct": None,
        "period_correct": None,
        "growth_direction_correct": None,
        "negative_condition_preserved": None,
        "ai_summary_accurate": None,
        "over_summary_misunderstanding_or_omission": "",
        "can_be_trusted_by_text": None,
        "not_trusted_reason": "",
        "should_add_to_regression_set": None,
        "reviewer_note": "",
    }


def _build_summary(output_dir: Path, machine_precheck: list[dict[str, Any]], review_queue: list[dict[str, Any]], candidate_count: int) -> dict[str, Any]:
    categories = Counter(category for row in machine_precheck for category in row["categories"])
    risks = Counter(label for row in machine_precheck for label in row["ai_precheck"]["risk_labels"])
    return {
        "review_id": "parse_lab_round3_text_parsing_quality_review",
        "output_dir": str(output_dir),
        "generated_at": datetime.utcnow().isoformat(),
        "raw_candidate_count": candidate_count,
        "sample_count": len(machine_precheck),
        "human_review_queue_count": len(review_queue),
        "sample_count_note": "target_150_250_met" if 150 <= len(machine_precheck) <= 250 else "all_available_relevant_texts_used",
        "category_distribution": dict(categories),
        "risk_label_distribution": dict(risks),
        "trusted_by_text_policy": "financial report text is not automatically trusted; high-risk or uncertain snippets require human review",
        "interpretation_policy": "sentiment or strategy summaries are interpretation candidates and do not replace source evidence_text",
    }


def _write_outputs(output_dir: Path, machine_precheck: list[dict[str, Any]], review_queue: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    _write_json(output_dir / "text_quality_machine_precheck.json", {"items": machine_precheck, "count": len(machine_precheck)})
    _write_jsonl(output_dir / "text_quality_human_review_template.jsonl", review_queue)
    _write_json(output_dir / "text_quality_sample_summary.json", summary)
    _write_html(output_dir / "text_quality_review_index.html", machine_precheck, review_queue)


def _write_html(path: Path, samples: list[dict[str, Any]], review_queue: list[dict[str, Any]]) -> None:
    data_json = json.dumps({"samples": samples, "reviewQueue": review_queue}, ensure_ascii=False)
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Text Parsing Quality Review</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; background: #f7f7f8; color: #1f2328; }}
    header {{ padding: 16px 20px; background: #20242c; color: white; }}
    main {{ display: grid; grid-template-columns: 280px 1fr; min-height: calc(100vh - 58px); }}
    aside {{ overflow: auto; border-right: 1px solid #ddd; background: white; padding: 12px; }}
    section {{ padding: 18px; overflow: auto; }}
    button {{ cursor: pointer; margin: 3px; padding: 7px 9px; border: 1px solid #bbb; background: white; border-radius: 4px; }}
    button.active {{ background: #0f766e; color: white; }}
    .panel {{ background: white; border: 1px solid #ddd; border-radius: 6px; padding: 14px; margin-bottom: 12px; }}
    .text {{ white-space: pre-wrap; line-height: 1.45; max-height: 220px; overflow: auto; background: #fafafa; border: 1px solid #e5e5e5; padding: 10px; }}
    .tag {{ display: inline-block; padding: 2px 6px; margin: 2px; border-radius: 4px; background: #e5e7eb; font-size: 12px; }}
    .risk {{ background: #fee2e2; }}
    label {{ display: block; margin: 10px 0; }}
    select, textarea {{ width: 100%; box-sizing: border-box; margin-top: 4px; }}
    textarea {{ min-height: 58px; }}
    .ai {{ font-size: 12px; color: #555; margin-top: 3px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(240px, 1fr)); gap: 10px; }}
  </style>
</head>
<body>
<header><strong>Text Parsing Quality Review</strong> <span id="counter"></span></header>
<main>
  <aside><div id="sampleList"></div></aside>
  <section>
    <div class="panel">
      <button id="prevBtn">Prev</button>
      <button id="nextBtn">Next</button>
      <button id="saveBtn">Save review</button>
      <button id="exportBtn">Export saved reviews</button>
    </div>
    <div id="content"></div>
  </section>
</main>
<script id="review-data" type="application/json">{html.escape(data_json)}</script>
<script>
const data = JSON.parse(document.getElementById('review-data').textContent);
let index = 0;
function storageKey(id) {{ return 'text_quality_review:' + id; }}
function saved(id) {{ return JSON.parse(localStorage.getItem(storageKey(id)) || '{{}}'); }}
function renderList() {{
  const list = document.getElementById('sampleList');
  list.innerHTML = '';
  data.samples.forEach((sample, i) => {{
    const btn = document.createElement('button');
    btn.textContent = `${{i + 1}} ${{sample.review_priority}} ${{sample.sample_id}}`;
    btn.className = i === index ? 'active' : '';
    btn.onclick = () => {{ index = i; render(); }};
    list.appendChild(btn);
  }});
}}
function field(name, label, aiValue) {{
  const current = saved(data.samples[index].sample_id)[name] ?? '';
  return `<label>${{label}}<div class="ai">AI pre-check: ${{aiValue}}</div>
    <select data-field="${{name}}">
      <option value="">unreviewed</option><option value="true" ${{current === true ? 'selected' : ''}}>true</option><option value="false" ${{current === false ? 'selected' : ''}}>false</option>
    </select></label>`;
}}
function textField(name, label) {{
  const current = saved(data.samples[index].sample_id)[name] || '';
  return `<label>${{label}}<textarea data-field="${{name}}">${{current}}</textarea></label>`;
}}
function render() {{
  renderList();
  const sample = data.samples[index];
  document.getElementById('counter').textContent = `${{index + 1}} / ${{data.samples.length}}`;
  const ai = sample.ai_precheck;
  document.getElementById('content').innerHTML = `
    <div class="panel"><strong>${{sample.sample_id}}</strong> | ${{sample.source_pdf}} p${{sample.source_page}} | ${{sample.source_kind}}</div>
    <div class="panel"><h3>Original Text</h3><div class="text">${{escapeHtml(sample.raw_text)}}</div></div>
    <div class="panel"><h3>Parsed Text</h3><div class="text">${{escapeHtml(sample.parsed_text)}}</div></div>
    <div class="panel"><h3>AI Summary</h3><div>${{escapeHtml(sample.ai_summary)}}</div></div>
    <div class="panel"><h3>AI Pre-check</h3>
      <div>${{ai.risk_labels.map(x => `<span class="tag risk">${{x}}</span>`).join('')}}</div>
      <pre>${{escapeHtml(JSON.stringify(ai, null, 2))}}</pre>
    </div>
    <div class="panel"><h3>Human Review</h3><div class="grid">
      ${{field('original_text_complete', '原文是否完整', ai.parsed_text_complete)}}
      ${{field('numbers_correct', '数字是否正确', ai.numeric_identification_ok)}}
      ${{field('unit_currency_percent_correct', '单位 / 币种 / 百分比是否正确', ai.unit_currency_identification_ok)}}
      ${{field('period_correct', '时间周期是否正确', ai.period_identification_ok)}}
      ${{field('growth_direction_correct', '同比/环比/方向是否正确', ai.growth_direction_identification_ok)}}
      ${{field('negative_condition_preserved', '否定词/限制条件是否保留', ai.negative_or_condition_preserved)}}
      ${{field('ai_summary_accurate', 'AI summary 是否准确', sample.ai_summary)}}
      ${{field('can_be_trusted_by_text', '是否可作为 trusted_by_text', ai.trusted_by_text_candidate)}}
      ${{field('should_add_to_regression_set', '是否加入 regression set', 'manual decision')}}
    </div>
      ${{textField('over_summary_misunderstanding_or_omission', '是否有过度总结、误解、遗漏')}}
      ${{textField('not_trusted_reason', '如果不可 trusted，原因是什么')}}
      ${{textField('reviewer_note', 'Reviewer note')}}
    </div>`;
}}
function save() {{
  const sample = data.samples[index];
  const payload = {{ sample_id: sample.sample_id, ai_precheck_snapshot: sample.ai_precheck, saved_at: new Date().toISOString() }};
  document.querySelectorAll('[data-field]').forEach(el => {{
    if (el.tagName === 'SELECT') payload[el.dataset.field] = el.value === '' ? null : el.value === 'true';
    else payload[el.dataset.field] = el.value;
  }});
  localStorage.setItem(storageKey(sample.sample_id), JSON.stringify(payload));
}}
function exportSaved() {{
  const rows = data.samples.map(s => saved(s.sample_id)).filter(x => x.sample_id);
  const blob = new Blob([JSON.stringify(rows, null, 2)], {{type: 'application/json'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'text_quality_human_reviews.json';
  a.click();
}}
function escapeHtml(s) {{ return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); }}
document.getElementById('prevBtn').onclick = () => {{ save(); index = Math.max(0, index - 1); render(); }};
document.getElementById('nextBtn').onclick = () => {{ save(); index = Math.min(data.samples.length - 1, index + 1); render(); }};
document.getElementById('saveBtn').onclick = save;
document.getElementById('exportBtn').onclick = exportSaved;
render();
</script>
</body>
</html>""",
        encoding="utf-8",
    )


def _classify_categories(text: str) -> list[str]:
    normalized = text.lower()
    categories = []
    if _has_number(text) or any(keyword in normalized for keyword in FINANCIAL_NUMERIC_KEYWORDS):
        categories.append("financial_numeric")
    if any(keyword in normalized for keyword in EXPLANATION_KEYWORDS):
        categories.append("financial_explanation")
    if any(keyword in normalized for keyword in SENTIMENT_STRATEGY_KEYWORDS):
        categories.append("sentiment_strategy")
    if _has_complex_language(text):
        categories.append("complex_language")
    if not categories:
        categories.append("low_risk")
    return categories


def _risk_labels(text: str, categories: list[str]) -> list[str]:
    labels = []
    if _has_numeric_parse_risk(text):
        labels.append("numeric_parse_risk")
    if _has_unit_currency_risk(text):
        labels.append("unit_currency_risk")
    if _has_period_risk(text):
        labels.append("period_risk")
    if _has_growth_direction_risk(text):
        labels.append("growth_direction_risk")
    if _has_negative_or_condition_risk(text):
        labels.append("negative_or_condition_missing_risk")
    if _has_sentence_boundary_risk(text):
        labels.append("sentence_boundary_risk")
    if _has_mixed_language_risk(text):
        labels.append("mixed_language_risk")
    if "sentiment_strategy" in categories:
        labels.append("sentiment_or_strategy_summary_risk")
    if _has_missing_context_risk(text):
        labels.append("missing_context_risk")
    if "sentiment_strategy" in categories and _has_sentence_boundary_risk(text):
        labels.append("hallucinated_summary_risk")
    if "low_risk" in categories and "low_risk" not in labels:
        labels.append("low_risk")
    if not labels:
        labels.append("low_risk")
    return labels


def _risk_score(labels: list[str], text: str) -> int:
    weights = {
        "numeric_parse_risk": 2,
        "unit_currency_risk": 2,
        "period_risk": 2,
        "growth_direction_risk": 2,
        "negative_or_condition_missing_risk": 2,
        "sentence_boundary_risk": 1,
        "mixed_language_risk": 1,
        "sentiment_or_strategy_summary_risk": 1,
        "missing_context_risk": 1,
        "hallucinated_summary_risk": 2,
        "low_risk": 0,
    }
    return sum(weights[label] for label in labels) + min(2, len(re.findall(r"\d", text)) // 20)


def _risk_seed(text: str) -> int:
    return _risk_score(_risk_labels(text, _classify_categories(text)), text)


def _trusted_by_text_candidate(labels: list[str], categories: list[str]) -> bool:
    disallowed = set(labels) - {"low_risk", "mixed_language_risk"}
    return not disallowed and "financial_numeric" in categories


def _one_sentence_summary(text: str, categories: list[str]) -> str:
    clean = _clean_text(text)
    first_sentence = re.split(r"(?<=[。.!?])\s+", clean)[0][:220]
    if "sentiment_strategy" in categories:
        return f"Interpretation candidate: {first_sentence}"
    return first_sentence


def _has_number(text: str) -> bool:
    return bool(re.search(r"\d", text))


def _has_numeric_parse_risk(text: str) -> bool:
    return bool(re.search(r"\d\s*,\s*\d{3}|\d+\.\s+\d+|\d\s+\d\s+\d", text))


def _has_unit_currency_risk(text: str) -> bool:
    normalized = text.lower()
    has_amount = bool(re.search(r"\d", text)) and any(token in normalized for token in ("rmb", "人民", "港元", "元", "million", "千", "百萬", "百万"))
    return has_amount and not any(token in normalized for token in ("rmb", "人民幣", "人民币", "cny", "hk$", "hkd", "港元", "usd", "美元"))


def _has_period_risk(text: str) -> bool:
    normalized = text.lower()
    return bool(re.search(r"20\d{2}|first half|reporting period|年度|半年|中期|報告期|报告期", normalized)) and bool(re.search(r"\d\s+月|\d\s+年|20\s*2\s*\d", text))


def _has_growth_direction_risk(text: str) -> bool:
    normalized = text.lower()
    return any(token in normalized for token in ("increase", "decrease", "growth", "decline", "同比", "环比", "上升", "下降", "增加", "减少", "增長", "減少"))


def _has_negative_or_condition_risk(text: str) -> bool:
    normalized = text.lower()
    return any(token in normalized for token in (*UNCERTAINTY_OR_CONDITION_KEYWORDS, *NEGATIVE_KEYWORDS))


def _has_sentence_boundary_risk(text: str) -> bool:
    return "<br>" in text or "\n" in text or bool(re.search(r"(?:[A-Za-z]\s*\n\s*){4,}", text)) or len(re.findall(r"\s", text)) > len(text) * 0.35


def _has_mixed_language_risk(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text)) and bool(re.search(r"[\u4e00-\u9fff]", text))


def _has_missing_context_risk(text: str) -> bool:
    clean = _clean_text(text)
    return len(clean) < 45 or clean.endswith((",", "，", "and", "or", "及", "與", "与", "from", "to"))


def _has_complex_language(text: str) -> bool:
    normalized = text.lower()
    return (
        _has_negative_or_condition_risk(text)
        or _has_growth_direction_risk(text)
        or _has_mixed_language_risk(text)
        or "<br>" in text
        or len(re.findall(r"\d", text)) >= 8
        or any(token in normalized for token in ("first half", "year-on-year", "reporting period", "同比", "环比", "報告期", "报告期"))
    )


def _chunk_text(text: str) -> list[str]:
    cleaned = _clean_text(text)
    parts = re.split(r"(?<=[。.!?])\s+|\n{2,}", cleaned)
    chunks = []
    for part in parts:
        part = part.strip()
        if 80 <= len(part) <= 900:
            chunks.append(part)
        elif len(part) > 900:
            for start in range(0, min(len(part), 3000), 650):
                chunk = part[start : start + 800].strip()
                if len(chunk) >= 80:
                    chunks.append(chunk)
    return chunks[:8]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("<br>", " ")).strip()


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        text = candidate["parsed_text"]
        if len(text) < 30:
            continue
        key = _fingerprint(text)
        existing = deduped.get(key)
        if existing is None or candidate["risk_seed"] > existing["risk_seed"]:
            deduped[key] = candidate
    return list(deduped.values())


def _fingerprint(text: str) -> str:
    normalized = re.sub(r"\W+", "", text.lower())[:300]
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
