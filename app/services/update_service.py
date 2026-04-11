import json
from typing import Dict, List, Optional

from config.settings import SCHEMA_VERSION
from services.provider_service import call_agent_chat
from services.research_utils import extract_metric_candidates, now_iso, safe_json_loads, truncate_text
from services.analysis_service import report_json_to_markdown
from services.industry_profile_service import infer_profile_from_extracted_materials
from utils.file_utils import get_company_folder
from services.json_repair_service import repair_json_payload
from services.period_service import period_sort_tuple
from services.company_profile_service import refresh_company_profile_snapshot

MODULE_KEYS = [
    "industry_positioning", "macro_environment", "company_overview", "cost_analysis", "customer_analysis",
    "profit_engine", "cash_flow_and_capital", "future_outlook", "moat", "risk_analysis", "forecast", "final_conclusion",
]


def _history_sort_key(data: dict):
    return (period_sort_tuple(data.get("related_primary_period_key") or data.get("period_key", "")), data.get("material_timestamp", ""), data.get("document_type", ""))


def build_history_facts_summary(historical_extracted_list: List[dict]) -> List[dict]:
    items = []
    for data in sorted(historical_extracted_list, key=_history_sort_key):
        items.append({
            "source_file": data.get("source_file", ""),
            "period_key": data.get("period_key", ""),
            "related_primary_period_key": data.get("related_primary_period_key", data.get("period_key", "")),
            "material_timestamp": data.get("material_timestamp", ""),
            "report_type": data.get("report_type", "UNKNOWN"),
            "document_type": data.get("document_type", "other_disclosure"),
            "timeline_bucket": data.get("timeline_bucket", "auxiliary"),
            "is_primary_financial_report": data.get("is_primary_financial_report", False),
            "forecast_target_period": data.get("forecast_target_period", ""),
            "key_sections": {
                "management_discussion_snippet": truncate_text(data.get("key_sections", {}).get("管理层讨论与分析片段", ""), 1800),
                "risk_snippet": truncate_text(data.get("key_sections", {}).get("风险因素片段", ""), 1800),
            },
        })
    return items


def build_history_judgment_summary(historical_report_list: List[dict]) -> List[dict]:
    items = []
    for report in sorted(historical_report_list, key=_history_sort_key):
        items.append({
            "source_file": report.get("source_file", ""),
            "period_key": report.get("period_key", ""),
            "related_primary_period_key": report.get("related_primary_period_key", report.get("period_key", "")),
            "material_timestamp": report.get("material_timestamp", ""),
            "document_type": report.get("document_type", "other_disclosure"),
            "timeline_bucket": report.get("timeline_bucket", "auxiliary"),
            "industry_positioning": report.get("industry_positioning", {}),
            "quantitative_snapshot": report.get("quantitative_snapshot", {}),
            "risk_analysis": report.get("risk_analysis", {}),
            "forecast": report.get("forecast", {}),
            "final_conclusion": report.get("final_conclusion", {}),
        })
    return items


def build_last_report_summary(last_report: dict) -> dict:
    if not last_report:
        return {}
    return {
        "period_key": last_report.get("period_key", ""),
        "related_primary_period_key": last_report.get("related_primary_period_key", last_report.get("period_key", "")),
        "material_timestamp": last_report.get("material_timestamp", ""),
        "document_type": last_report.get("document_type", ""),
        "quantitative_snapshot": last_report.get("quantitative_snapshot", {}),
        "risk_analysis": last_report.get("risk_analysis", {}),
        "forecast": last_report.get("forecast", {}),
        "final_conclusion": last_report.get("final_conclusion", {}),
    }


def build_latest_context(latest_parsed: dict, latest_extracted: dict) -> dict:
    return {
        "company_name": latest_extracted.get("company_name", ""),
        "source_file": latest_extracted.get("source_file", ""),
        "fiscal_year": latest_extracted.get("fiscal_year"),
        "report_type": latest_extracted.get("report_type", "UNKNOWN"),
        "period_key": latest_extracted.get("period_key", ""),
        "related_primary_period_key": latest_extracted.get("related_primary_period_key", latest_extracted.get("period_key", "")),
        "document_type": latest_extracted.get("document_type", "other_disclosure"),
        "timeline_bucket": latest_extracted.get("timeline_bucket", "auxiliary"),
        "report_date": latest_extracted.get("report_date", ""),
        "material_timestamp": latest_extracted.get("material_timestamp", ""),
        "is_primary_financial_report": latest_extracted.get("is_primary_financial_report", False),
        "forecast_as_of_period": latest_extracted.get("forecast_as_of_period", ""),
        "forecast_target_period": latest_extracted.get("forecast_target_period", ""),
        "management_discussion_snippet": truncate_text(latest_extracted.get("key_sections", {}).get("管理层讨论与分析片段", ""), 2400),
        "risk_snippet": truncate_text(latest_extracted.get("key_sections", {}).get("风险因素片段", ""), 2400),
        "latest_full_text_preview": truncate_text(latest_parsed.get("full_text", ""), 20000),
        "latest_metric_candidates": extract_metric_candidates(latest_parsed.get("full_text", ""))[:20],
    }


def build_update_system_prompt() -> str:
    return """
你是一名财报研究更新助手。
你不是在“修补上一版报告”，而是在某个信息时点 a，基于当时全部已知材料，重建一份最新版研究报告。

你会同时看到：
- 历史事实（historical extracted）
- 历史判断（historical report）
- 上一期报告（如果有）
- 历史记忆（如果有）
- 最新 parsed / extracted

方法要求：
1. 最新材料优先于历史材料，但不能无视历史累计误差与过去失效判断。
2. 主财报负责“实线”；辅助材料负责“虚线引导”，用于补充事实、修正口径、提示风险与提前修正预期。
3. 辅助材料绝不能冒充主时序正式财报事实，更不能写入 actuals 意义上的最终实现值。
4. 输出的 master_report 必须体现“站在当前时点，拿着当时全部材料”的完整公司认知。
5. delta_report 必须说明：这次新材料对研究框架、判断、监测指标和风险认知造成了什么变化。
6. 如果发现过去判断不对，要明确写出修正，而不是平滑带过。
7. 输出必须是纯 JSON，不能有 Markdown、解释或注释。

输出顶层必须只有两个键：
{"master_report": { ... }, "delta_report": { ... }}
""".strip()


def build_update_user_prompt(latest_context: dict, history_facts_summary: list, history_judgment_summary: list, last_report_summary: dict, previous_history_memory: Optional[dict]) -> str:
    payload = {
        "latest_context": latest_context,
        "history_facts_summary": history_facts_summary,
        "history_judgment_summary": history_judgment_summary,
        "last_report_summary": last_report_summary,
        "previous_history_memory": previous_history_memory or {},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_history_memory(history_facts_summary: list, history_judgment_summary: list, latest_context: dict, master_report: dict, delta_report: dict, previous_history_memory: Optional[dict] = None) -> dict:
    logs = [] if not previous_history_memory else previous_history_memory.get("update_logs", [])
    logs.append({
        "generated_at": now_iso(),
        "actual_period_key": delta_report.get("actual_period_key", ""),
        "material_timestamp": latest_context.get("material_timestamp", ""),
        "summary": delta_report.get("summary", ""),
        "watch_points": delta_report.get("watch_points", []),
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "history_facts_summary": history_facts_summary,
        "history_judgment_summary": history_judgment_summary,
        "latest_context_snapshot": latest_context,
        "latest_master_report_summary": {
            "period_key": master_report.get("period_key", ""),
            "related_primary_period_key": master_report.get("related_primary_period_key", master_report.get("period_key", "")),
            "material_timestamp": master_report.get("material_timestamp", ""),
            "industry_positioning": master_report.get("industry_positioning", {}),
            "quantitative_snapshot": master_report.get("quantitative_snapshot", {}),
            "risk_analysis": master_report.get("risk_analysis", {}),
            "forecast": master_report.get("forecast", {}),
            "final_conclusion": master_report.get("final_conclusion", {}),
        },
        "latest_delta_report": delta_report,
        "update_logs": logs,
    }


def generate_updated_master_report(latest_parsed: dict, latest_extracted: dict, historical_extracted_list: List[dict], historical_report_list: List[dict], last_report: dict, previous_history_memory: Optional[dict] = None) -> dict:
    latest_context = build_latest_context(latest_parsed, latest_extracted)
    profile_tags = infer_profile_from_extracted_materials(historical_extracted_list + [latest_extracted])
    latest_context["profile_tags"] = profile_tags
    company_name = latest_extracted.get("company_name", "")
    if company_name:
        try:
            refresh_company_profile_snapshot(get_company_folder(company_name), profile_tags, refresh_reason="update")
        except Exception:
            pass
    history_facts_summary = build_history_facts_summary(historical_extracted_list)
    history_judgment_summary = build_history_judgment_summary(historical_report_list)
    last_report_summary = build_last_report_summary(last_report)
    raw = call_agent_chat("update_agent", build_update_system_prompt(), build_update_user_prompt(latest_context, history_facts_summary, history_judgment_summary, last_report_summary, previous_history_memory))
    try:
        payload = safe_json_loads(raw)
    except Exception as exc:
        payload = repair_json_payload(raw, expected_top_keys=["master_report", "delta_report"])
    master_report = payload.get("master_report", {})
    delta_report = payload.get("delta_report", {})

    master_report["schema_version"] = SCHEMA_VERSION
    master_report["generated_at"] = now_iso()
    for key in ["company_name", "source_file", "fiscal_year", "report_type", "period_key", "related_primary_period_key", "document_type", "timeline_bucket", "report_date", "material_timestamp", "is_annual_final", "is_primary_financial_report", "can_adjust_forecast", "forecast_as_of_period", "forecast_target_period"]:
        if master_report.get(key) in [None, "", []] and key in latest_extracted:
            master_report[key] = latest_extracted.get(key)
    master_report.setdefault("profile_tags", profile_tags)
    master_report.setdefault("quantitative_snapshot", {})
    master_report["quantitative_snapshot"].setdefault("candidate_metrics", latest_context.get("latest_metric_candidates", []))

    delta_report["schema_version"] = SCHEMA_VERSION
    delta_report["company_name"] = latest_extracted.get("company_name", "")
    delta_report["base_period_key"] = (last_report or {}).get("period_key", "")
    delta_report["actual_period_key"] = latest_extracted.get("period_key", "")
    delta_report["actual_document_type"] = latest_extracted.get("document_type", "other_disclosure")
    delta_report["forecast_target_period"] = latest_extracted.get("forecast_target_period", "")
    delta_report["previous_report_exists"] = bool(last_report)

    history_memory = build_history_memory(history_facts_summary, history_judgment_summary, latest_context, master_report, delta_report, previous_history_memory)
    return {"master_report": master_report, "delta_report": delta_report, "history_memory": history_memory}


def master_report_to_markdown(master_report: dict) -> str:
    return report_json_to_markdown(master_report)
