import json
from typing import Any, Dict, List

from config.settings import DEFAULT_FULLTEXT_PREVIEW_CHARS, SCHEMA_VERSION
from services.industry_profile_service import infer_profile_from_extracted_materials
from services.company_profile_service import refresh_company_profile_snapshot
from utils.file_utils import get_company_folder
from services.json_repair_service import repair_json_payload
from services.period_service import period_sort_tuple
from services.provider_service import call_agent_chat
from services.research_utils import ensure_list, extract_metric_candidates, now_iso, safe_json_loads, truncate_text

ANALYSIS_JSON_TEMPLATE = {
    "schema_version": SCHEMA_VERSION,
    "generated_at": "",
    "source_doc_id": "",
    "company_name": "",
    "source_file": "",
    "fiscal_year": None,
    "report_type": "",
    "period_key": "",
    "document_type": "",
    "report_date": "",
    "material_timestamp": "",
    "material_timestamp_precision": "",
    "is_annual_final": False,
    "is_primary_financial_report": False,
    "can_adjust_forecast": False,
    "forecast_as_of_period": "",
    "forecast_target_period": "",
    "analysis_scope": {
        "analysis_mode": "single_or_multi_material",
        "material_count": 0,
        "anchor_source_file": "",
        "anchor_period_key": "",
        "anchor_material_timestamp": "",
        "selection_rule": "主时间轴以最新主财报为锚点；辅助材料只补充，不改主线。"
    },
    "selected_materials": [],
    "profile_tags": {},
    "quantitative_snapshot": {"data_quality": "高/中/低/信息不足", "candidate_metrics": [], "notes": []},
    "industry_positioning": {},
    "macro_environment": {},
    "company_overview": {},
    "cost_analysis": {},
    "customer_analysis": {},
    "profit_engine": {},
    "cash_flow_and_capital": {},
    "future_outlook": {},
    "moat": {},
    "risk_analysis": {},
    "forecast": {},
    "final_conclusion": {},
}


def _material_anchor_sort_key(extracted_data: dict):
    if extracted_data.get("is_primary_financial_report") and extracted_data.get("period_key"):
        year, order, label = period_sort_tuple(extracted_data.get("period_key", ""))
        return (0, year, order, extracted_data.get("material_timestamp", ""), extracted_data.get("report_date", ""), label)
    fiscal_year = extracted_data.get("fiscal_year") or 0
    report_type = extracted_data.get("report_type", "UNKNOWN")
    report_order = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}.get(report_type, 9)
    return (1, fiscal_year, report_order, extracted_data.get("material_timestamp", ""), extracted_data.get("report_date", ""), extracted_data.get("source_file", ""))


def select_analysis_anchor(extracted_materials: List[dict]) -> dict:
    if not extracted_materials:
        return {}
    primary = [item for item in extracted_materials if item.get("is_primary_financial_report")]
    candidates = primary if primary else extracted_materials
    return max(candidates, key=_material_anchor_sort_key)


def _merge_metric_candidates(parsed_materials: List[dict], limit: int = 30) -> list:
    merged = []
    seen = set()
    for parsed_data in parsed_materials:
        source_file = parsed_data.get("source_file", "")
        for item in extract_metric_candidates(parsed_data.get("full_text", "")):
            metric_key = item.get("metric_key", "")
            snippet = item.get("snippet", "")
            dedup_key = (metric_key, snippet)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            merged.append({"metric_key": metric_key, "snippet": snippet, "source_file": source_file})
            if len(merged) >= limit:
                return merged
    return merged


def _build_material_entry(parsed_data: dict, extracted_data: dict) -> dict:
    key_sections = extracted_data.get("key_sections", {})
    return {
        "source_file": extracted_data.get("source_file", parsed_data.get("source_file", "")),
        "fiscal_year": extracted_data.get("fiscal_year"),
        "report_type": extracted_data.get("report_type", "UNKNOWN"),
        "period_key": extracted_data.get("period_key", ""),
        "related_primary_period_key": extracted_data.get("related_primary_period_key", ""),
        "document_type": extracted_data.get("document_type", "other_disclosure"),
        "timeline_bucket": extracted_data.get("timeline_bucket", "other"),
        "report_date": extracted_data.get("report_date", ""),
        "material_timestamp": extracted_data.get("material_timestamp", ""),
        "material_timestamp_precision": extracted_data.get("material_timestamp_precision", ""),
        "is_primary_financial_report": extracted_data.get("is_primary_financial_report", False),
        "can_adjust_forecast": extracted_data.get("can_adjust_forecast", False),
        "forecast_as_of_period": extracted_data.get("forecast_as_of_period", ""),
        "forecast_target_period": extracted_data.get("forecast_target_period", ""),
        "page_count": parsed_data.get("page_count", 0),
        "dominant_language": parsed_data.get("dominant_language", extracted_data.get("dominant_language", "")),
        "title_candidates": extracted_data.get("title_candidates", [])[:6],
        "metric_candidates": extract_metric_candidates(parsed_data.get("full_text", ""))[:8],
        "management_discussion_snippet": truncate_text(key_sections.get("管理层讨论与分析片段", ""), 800),
        "risk_snippet": truncate_text(key_sections.get("风险因素片段", ""), 600),
        "full_text_preview": truncate_text(parsed_data.get("full_text", ""), DEFAULT_FULLTEXT_PREVIEW_CHARS),
    }


def build_analysis_context_for_materials(parsed_materials: List[dict], extracted_materials: List[dict]) -> str:
    anchor_extracted = select_analysis_anchor(extracted_materials)
    material_entries = [_build_material_entry(p, e) for p, e in zip(parsed_materials, extracted_materials)]
    material_entries = sorted(material_entries, key=lambda item: _material_anchor_sort_key(item))
    profile_tags = infer_profile_from_extracted_materials(extracted_materials)
    company_name = anchor_extracted.get("company_name", "")
    if company_name:
        try:
            refresh_company_profile_snapshot(get_company_folder(company_name), profile_tags, refresh_reason="analyze")
        except Exception:
            pass
    payload = {
        "analysis_scope": {
            "material_count": len(material_entries),
            "anchor_material": {
                "source_file": anchor_extracted.get("source_file", ""),
                "period_key": anchor_extracted.get("period_key", ""),
                "related_primary_period_key": anchor_extracted.get("related_primary_period_key", ""),
                "report_type": anchor_extracted.get("report_type", "UNKNOWN"),
                "document_type": anchor_extracted.get("document_type", "other_disclosure"),
                "timeline_bucket": anchor_extracted.get("timeline_bucket", "other"),
                "material_timestamp": anchor_extracted.get("material_timestamp", ""),
                "material_timestamp_precision": anchor_extracted.get("material_timestamp_precision", ""),
                "forecast_as_of_period": anchor_extracted.get("forecast_as_of_period", ""),
                "forecast_target_period": anchor_extracted.get("forecast_target_period", ""),
            },
            "selection_rule": "主时间轴只由最新主财报决定；辅助材料只能补充事实、口径和风险，不允许覆盖主时序。",
        },
        "profile_tags": profile_tags,
        "selected_materials": material_entries,
        "quantitative_candidates": _merge_metric_candidates(parsed_materials, limit=36),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_analysis_prompt() -> str:
    template = json.dumps(ANALYSIS_JSON_TEMPLATE, ensure_ascii=False, indent=2)
    return f"""
你是一名财报研究分析师，不需要讨好用户，只需要站在当前材料时点，告诉用户“当时是什么情况”。

这次输入可能包含同一家公司的多份材料。你必须遵守：
1. 以 `analysis_scope.anchor_material` 作为当前分析锚点。
2. 主时间轴只由最新主财报决定；辅助材料只能补充事实、风险、管理层口径和验证信息，不能打乱主线。
3. `profile_tags` 只是帮助你避免欠拟合/过拟合的先验标签，不是绝对事实；若材料证据冲突，以材料为准。
4. 所有判断尽量给出量化依据；如果材料没有足够数据，就写“信息不足”。
5. 行业识别必须先行：一级/二级/三级分类；不确定就写“信息不足”。
6. 不要写空泛好听的话，不要把管理层口径直接当事实。
7. 预测部分必须给 bull/base/bear 三情景，并且每个情景都要给量化指标、触发条件、反证条件。
8. 必须明确这是“站在锚点时点，拿着当时全部已选材料”做出的判断，不允许引用未来信息。
9. 对辅助材料要特别注意 material_timestamp；同一年内不同月份的辅助材料，属于不同信息时点，不能混同。
10. 输出必须是纯 JSON，不要 Markdown，不要解释，不要在 JSON 外再包文字。

输出顶层结构参考：
{template}

字段要求补充：
- 顶层元数据默认继承 `analysis_scope.anchor_material`
- `profile_tags` 原样保留或根据证据微调
- `industry_positioning`：至少包含 `level_1` / `level_2` / `level_3` / `business_model` / `industry_specific_focus` / `evidence_items` / `confidence`
- 10 大模块都要尽量输出：`summary` / `quantitative_points` / `evidence_items` / `insufficiency_flags`
- `risk_analysis` 还要包含：`survival_risk_level` / `major_risks` / `monitoring_metrics`
- `forecast` 还要包含：`method` / `summary` / `bull_case` / `base_case` / `bear_case` / `key_signals_to_watch`
- `bull_case` / `base_case` / `bear_case` 每个都要有：`view` / `quantitative_targets` / `drivers` / `trigger_conditions` / `falsifiers`
- `final_conclusion` 要包含：`stance` / `summary` / `why_not_more_bullish` / `why_not_more_bearish`
""".strip()


def _post_process(report: dict, parsed_materials: List[dict], extracted_materials: List[dict]) -> dict:
    anchor_extracted = select_analysis_anchor(extracted_materials)
    report = report if isinstance(report, dict) else {}
    report["schema_version"] = SCHEMA_VERSION
    report["generated_at"] = now_iso()
    report["source_doc_id"] = report.get("source_doc_id") or anchor_extracted.get("source_file", "")

    anchor_defaults = {
        "company_name": anchor_extracted.get("company_name", ""),
        "source_file": anchor_extracted.get("source_file", ""),
        "fiscal_year": anchor_extracted.get("fiscal_year"),
        "report_type": anchor_extracted.get("report_type", "UNKNOWN"),
        "period_key": anchor_extracted.get("period_key", ""),
        "related_primary_period_key": anchor_extracted.get("related_primary_period_key", ""),
        "document_type": anchor_extracted.get("document_type", "other_disclosure"),
        "timeline_bucket": anchor_extracted.get("timeline_bucket", "other"),
        "report_date": anchor_extracted.get("report_date", ""),
        "material_timestamp": anchor_extracted.get("material_timestamp", ""),
        "material_timestamp_precision": anchor_extracted.get("material_timestamp_precision", ""),
        "is_annual_final": anchor_extracted.get("is_annual_final", False),
        "is_primary_financial_report": anchor_extracted.get("is_primary_financial_report", False),
        "can_adjust_forecast": anchor_extracted.get("can_adjust_forecast", False),
        "forecast_as_of_period": anchor_extracted.get("forecast_as_of_period", ""),
        "forecast_target_period": anchor_extracted.get("forecast_target_period", ""),
    }
    for key, value in anchor_defaults.items():
        if report.get(key) in [None, "", []]:
            report[key] = value

    report.setdefault("analysis_scope", {})
    report["analysis_scope"].setdefault("analysis_mode", "multi_material" if len(extracted_materials) > 1 else "single_material")
    report["analysis_scope"]["material_count"] = len(extracted_materials)
    report["analysis_scope"].setdefault("anchor_source_file", anchor_extracted.get("source_file", ""))
    report["analysis_scope"].setdefault("anchor_period_key", anchor_extracted.get("period_key", ""))
    report["analysis_scope"].setdefault("anchor_material_timestamp", anchor_extracted.get("material_timestamp", ""))
    report["analysis_scope"].setdefault("selection_rule", "主时间轴以最新主财报为锚点；辅助材料只补充，不改主线。")

    report["selected_materials"] = [
        {
            "source_file": e.get("source_file", ""),
            "period_key": e.get("period_key", ""),
            "related_primary_period_key": e.get("related_primary_period_key", ""),
            "report_type": e.get("report_type", "UNKNOWN"),
            "document_type": e.get("document_type", "other_disclosure"),
            "timeline_bucket": e.get("timeline_bucket", "other"),
            "material_timestamp": e.get("material_timestamp", ""),
            "material_timestamp_precision": e.get("material_timestamp_precision", ""),
            "is_primary_financial_report": e.get("is_primary_financial_report", False),
        }
        for e in extracted_materials
    ]
    report.setdefault("profile_tags", infer_profile_from_extracted_materials(extracted_materials))
    report.setdefault("quantitative_snapshot", {})
    report["quantitative_snapshot"].setdefault("candidate_metrics", _merge_metric_candidates(parsed_materials, limit=20))
    report["quantitative_snapshot"].setdefault("notes", [])
    report["quantitative_snapshot"].setdefault("data_quality", "信息不足")

    for key in [
        "industry_positioning", "macro_environment", "company_overview", "cost_analysis", "customer_analysis",
        "profit_engine", "cash_flow_and_capital", "future_outlook", "moat", "risk_analysis", "forecast", "final_conclusion",
    ]:
        if not isinstance(report.get(key), dict):
            report[key] = {}

    return report


def _coerce_report_object(payload: Any) -> dict:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        nested = safe_json_loads(payload)
        if isinstance(nested, dict):
            return nested
    raise ValueError(f"模型返回已解析，但顶层不是 JSON 对象，而是：{type(payload).__name__}")


def generate_financial_report_from_materials(parsed_materials: List[dict], extracted_materials: List[dict]) -> dict:
    if not parsed_materials or not extracted_materials:
        raise ValueError("parsed_materials 和 extracted_materials 不能为空。")
    if len(parsed_materials) != len(extracted_materials):
        raise ValueError("parsed_materials 和 extracted_materials 数量不一致。")

    context = build_analysis_context_for_materials(parsed_materials, extracted_materials)
    raw = call_agent_chat("analysis_agent", build_analysis_prompt(), context)
    try:
        report = _coerce_report_object(safe_json_loads(raw))
    except Exception as exc:
        try:
            report = repair_json_payload(raw, expected_top_keys=[
                "schema_version", "generated_at", "company_name", "period_key", "document_type",
                "analysis_scope", "selected_materials", "profile_tags", "quantitative_snapshot",
                "industry_positioning", "macro_environment", "company_overview", "cost_analysis",
                "customer_analysis", "profit_engine", "cash_flow_and_capital", "future_outlook",
                "moat", "risk_analysis", "forecast", "final_conclusion",
            ])
        except Exception as repair_exc:
            preview = truncate_text(raw, 1600)
            raise ValueError(
                f"模型返回的分析 JSON 无法解析；自动修复也失败。原始错误：{exc}；修复错误：{repair_exc}\n\n原始输出片段：\n{preview}"
            ) from repair_exc
    return _post_process(report, parsed_materials, extracted_materials)


def generate_financial_report(parsed_data: dict, extracted_data: dict) -> dict:
    return generate_financial_report_from_materials([parsed_data], [extracted_data])


def _normalize_list_of_text(value: Any) -> List[str]:
    if value is None:
        return []
    items = ensure_list(value)
    output = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("summary") or item.get("value") or item.get("name") or json.dumps(item, ensure_ascii=False)
            output.append(str(text))
        else:
            output.append(str(item))
    return [x for x in output if x and x != "None"]


def _normalize_metric_items(value: Any) -> List[dict]:
    items = ensure_list(value)
    normalized = []
    for item in items:
        if isinstance(item, dict):
            normalized.append(item)
        elif isinstance(item, str):
            normalized.append({"metric_key": "metric", "snippet": item})
        else:
            normalized.append({"metric_key": "metric", "snippet": str(item)})
    return normalized


def _section_to_markdown(title: str, section: Any) -> str:
    if not isinstance(section, dict):
        return f"## {title}\n\n信息不足\n"
    lines = [f"## {title}", ""]
    lines.append(str(section.get("summary", "信息不足") or "信息不足"))
    q_points = _normalize_list_of_text(section.get("quantitative_points", []))
    if q_points:
        lines.append("")
        lines.append("量化要点：")
        for item in q_points:
            lines.append(f"- {item}")
    evidence = _normalize_list_of_text(section.get("evidence_items", []))
    if evidence:
        lines.append("")
        lines.append("证据：")
        for item in evidence:
            lines.append(f"- {item}")
    insuff = _normalize_list_of_text(section.get("insufficiency_flags", []))
    if insuff:
        lines.append("")
        lines.append("信息不足：")
        for item in insuff:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def report_json_to_markdown(report_data: dict) -> str:
    if not isinstance(report_data, dict):
        raise ValueError(f"report_json_to_markdown 需要 dict，收到的是：{type(report_data).__name__}")

    lines: List[str] = []
    lines.append(f"# {report_data.get('company_name', '未命名公司')} - {report_data.get('period_key', '')} 研究报告")
    lines.append("")
    lines.append(f"- 生成时间：{report_data.get('generated_at', '')}")
    lines.append(f"- 分析锚点文件：{report_data.get('source_file', '')}")
    lines.append(f"- 文档类型：{report_data.get('document_type', '')}")
    lines.append(f"- 时间桶：{report_data.get('timeline_bucket', '')}")
    lines.append(f"- 材料时间戳：{report_data.get('material_timestamp', '')}")
    lines.append(f"- 时间戳精度：{report_data.get('material_timestamp_precision', '')}")
    lines.append(f"- 预测时点：{report_data.get('forecast_as_of_period', '')}")
    lines.append(f"- 预测目标：{report_data.get('forecast_target_period', '')}")
    lines.append("")

    analysis_scope = report_data.get("analysis_scope", {}) if isinstance(report_data.get("analysis_scope"), dict) else {}
    selected_materials = ensure_list(report_data.get("selected_materials", []))
    lines.append("## 分析范围")
    lines.append("")
    lines.append(f"- 分析模式：{analysis_scope.get('analysis_mode', '信息不足')}")
    lines.append(f"- 材料数量：{analysis_scope.get('material_count', len(selected_materials))}")
    lines.append(f"- 锚点文件：{analysis_scope.get('anchor_source_file', report_data.get('source_file', ''))}")
    lines.append(f"- 锚点 period_key：{analysis_scope.get('anchor_period_key', report_data.get('period_key', ''))}")
    lines.append(f"- 锚点时间戳：{analysis_scope.get('anchor_material_timestamp', report_data.get('material_timestamp', ''))}")
    if analysis_scope.get("selection_rule"):
        lines.append(f"- 选材规则：{analysis_scope.get('selection_rule')}")
    lines.append("")

    if selected_materials:
        lines.append("### 本次喂养材料")
        for item in selected_materials:
            item = item if isinstance(item, dict) else {"source_file": str(item)}
            label = item.get("source_file", "")
            meta = [
                f"period_key={item.get('period_key', '') or '空'}",
                f"related_primary={item.get('related_primary_period_key', '') or '空'}",
                f"report_type={item.get('report_type', 'UNKNOWN')}",
                f"document_type={item.get('document_type', 'other_disclosure')}",
                f"timeline={item.get('timeline_bucket', 'other')}",
                f"timestamp={item.get('material_timestamp', '') or '空'}",
                f"主财报={'是' if item.get('is_primary_financial_report') else '否'}",
            ]
            lines.append(f"- {label} ｜ " + " ｜ ".join(meta))
        lines.append("")

    profile_tags = report_data.get("profile_tags", {}) if isinstance(report_data.get("profile_tags"), dict) else {}
    if profile_tags:
        lines.append("## 公司定位标签")
        lines.append("")
        lines.append(f"- 行业层级：{profile_tags.get('level_1', '信息不足')} / {profile_tags.get('level_2', '信息不足')} / {profile_tags.get('level_3', '信息不足')}")
        lines.append(f"- 标签来源：{profile_tags.get('override_source', 'auto')}")
        for key, label in [("business_model", "商业模式"), ("value_chain", "价值链位势"), ("lifecycle", "生命周期"), ("disturbance", "特殊扰动")]:
            values = ensure_list((profile_tags.get("tag_summary", {}) or {}).get(key, []))
            if values:
                lines.append(f"- {label}：" + "；".join([str(x) for x in values]))
        lines.append("")

    qs = report_data.get("quantitative_snapshot", {}) if isinstance(report_data.get("quantitative_snapshot"), dict) else {}
    if qs:
        lines.append("## 量化快照")
        lines.append("")
        lines.append(f"数据质量：{qs.get('data_quality', '信息不足')}")
        for item in _normalize_metric_items(qs.get("candidate_metrics", []))[:12]:
            lines.append(f"- {item.get('metric_key', '')}: {item.get('snippet', '')}" + (f"（来源：{item.get('source_file', '')}）" if item.get("source_file") else ""))
        lines.append("")

    industry = report_data.get("industry_positioning", {}) if isinstance(report_data.get("industry_positioning"), dict) else {}
    lines.append("## 行业定位")
    lines.append("")
    lines.append(f"- 一级分类：{industry.get('level_1', profile_tags.get('level_1', '信息不足'))}")
    lines.append(f"- 二级分类：{industry.get('level_2', profile_tags.get('level_2', '信息不足'))}")
    lines.append(f"- 三级分类：{industry.get('level_3', profile_tags.get('level_3', '信息不足'))}")
    lines.append(f"- 商业模式：{industry.get('business_model', '信息不足')}")
    focus = _normalize_list_of_text(industry.get("industry_specific_focus", []))
    if focus:
        lines.append("- 行业关注点：" + "；".join(focus))
    lines.append("")

    for key, title in [
        ("macro_environment", "宏观环境"),
        ("company_overview", "公司概况"),
        ("cost_analysis", "成本结构"),
        ("customer_analysis", "客户结构"),
        ("profit_engine", "盈利模式"),
        ("cash_flow_and_capital", "资金流向"),
        ("future_outlook", "未来展望"),
        ("moat", "护城河"),
        ("risk_analysis", "风险分析"),
    ]:
        lines.append(_section_to_markdown(title, report_data.get(key, {})))

    forecast = report_data.get("forecast", {}) if isinstance(report_data.get("forecast"), dict) else {}
    lines.append("## 风险 + 预期")
    lines.append("")
    lines.append(str(forecast.get("summary", "信息不足") or "信息不足"))
    lines.append("")

    final_conclusion = report_data.get("final_conclusion", {}) if isinstance(report_data.get("final_conclusion"), dict) else {}
    lines.append("## 结论")
    lines.append("")
    lines.append(str(final_conclusion.get("summary", "信息不足") or "信息不足"))
    lines.append("")
    return "\n".join(lines)
