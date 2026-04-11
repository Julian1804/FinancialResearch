from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import SCHEMA_VERSION
from services.period_service import period_sort_tuple
from services.research_utils import now_iso
from utils.file_utils import build_history_memory_path, load_json_file, save_json_file


MATCH_LEVEL_SCORE = {
    "符合": 3,
    "部分符合": 2,
    "明显偏离": 1,
    "信息不足": 0,
}


def _analysis_dir(company_folder: str | Path) -> Path:
    company_folder = Path(company_folder)
    path = company_folder / "年报分析"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _revision_log_path(company_folder: str | Path) -> Path:
    return _analysis_dir(company_folder) / "backtest_revision_log.json"


def _forecast_check_files(company_folder: str | Path) -> List[Path]:
    return sorted(_analysis_dir(company_folder).glob("forecast_check_*.json"))


def _safe_load_json(path: Path) -> dict:
    try:
        return load_json_file(path)
    except Exception:
        return {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _match_score(level: str) -> int:
    return MATCH_LEVEL_SCORE.get(level or "", 0)


def _normalize_forecast_check_entry(item: dict, file_path: str = "") -> dict:
    deviation_pct = _safe_float(item.get("deviation_pct"))
    if deviation_pct is None:
        deviation_pct = _safe_float(item.get("deviation_pct_display"))
        if deviation_pct is not None:
            deviation_pct = deviation_pct / 100.0

    entry = {
        "generated_at": item.get("generated_at", ""),
        "company_name": item.get("company_name", ""),
        "metric_name": item.get("metric_name", ""),
        "forecast_as_of_period": item.get("forecast_as_of_period", ""),
        "forecast_target_period": item.get("forecast_target_period", ""),
        "actual_observation_period": item.get("actual_observation_period", ""),
        "actual_document_type": item.get("actual_document_type", ""),
        "snapshot_used": item.get("snapshot_used", False),
        "comparison_basis": item.get("comparison_basis", ""),
        "prediction_match_level": item.get("prediction_match_level", "信息不足"),
        "prediction_match_score": _match_score(item.get("prediction_match_level", "")),
        "actual_current_value": _safe_float(item.get("actual_current_value")),
        "expected_current_value": _safe_float(item.get("expected_current_value")),
        "snapshot_base_value": _safe_float(item.get("snapshot_base_value")),
        "snapshot_bull_value": _safe_float(item.get("snapshot_bull_value")),
        "snapshot_bear_value": _safe_float(item.get("snapshot_bear_value")),
        "deviation_abs": _safe_float(item.get("deviation_abs")),
        "deviation_pct": deviation_pct,
        "previous_recommendation": item.get("previous_recommendation", ""),
        "updated_recommendation": item.get("updated_recommendation", ""),
        "summary": item.get("summary", ""),
        "matched_points": item.get("matched_points", []),
        "missed_points": item.get("missed_points", []),
        "surprise_points": item.get("surprise_points", []),
        "deviation_sources": item.get("deviation_sources", {}),
        "framework_feedback": item.get("framework_feedback", {}),
        "source_file_path": file_path,
    }
    return entry


def load_all_forecast_check_entries(company_folder: str | Path) -> List[dict]:
    rows = []
    for path in _forecast_check_files(company_folder):
        data = _safe_load_json(path)
        if data:
            rows.append(_normalize_forecast_check_entry(data, str(path)))
    rows.sort(
        key=lambda x: (
            x.get("forecast_target_period", ""),
            x.get("metric_name", ""),
            period_sort_tuple(x.get("actual_observation_period", "")),
            x.get("generated_at", ""),
        )
    )
    return rows


def _group_key(entry: dict) -> Tuple[str, str]:
    return (
        entry.get("forecast_target_period", "") or "UNKNOWN_TARGET",
        entry.get("metric_name", "") or "UNKNOWN_METRIC",
    )


def _summarize_target_group(entries: List[dict]) -> dict:
    if not entries:
        return {
            "forecast_target_period": "",
            "record_count": 0,
            "metric_count": 0,
            "avg_match_score": None,
            "avg_abs_deviation_pct": None,
            "latest_observation_period": "",
            "latest_summary": "",
            "risk_level": "信息不足",
        }

    target = entries[0].get("forecast_target_period", "")
    metric_names = sorted(list({e.get("metric_name", "") for e in entries if e.get("metric_name", "")}))
    scores = [e.get("prediction_match_score", 0) for e in entries]
    deviations = [abs(e.get("deviation_pct")) * 100 for e in entries if e.get("deviation_pct") is not None]

    latest = sorted(
        entries,
        key=lambda x: (
            period_sort_tuple(x.get("actual_observation_period", "")),
            x.get("generated_at", ""),
        )
    )[-1]

    avg_score = sum(scores) / len(scores) if scores else None
    avg_dev = sum(deviations) / len(deviations) if deviations else None

    risk_level = "低"
    if avg_score is not None and avg_score < 1.8:
        risk_level = "高"
    elif avg_score is not None and avg_score < 2.4:
        risk_level = "中"

    return {
        "forecast_target_period": target,
        "record_count": len(entries),
        "metric_count": len(metric_names),
        "metrics": metric_names,
        "avg_match_score": round(avg_score, 3) if avg_score is not None else None,
        "avg_abs_deviation_pct": round(avg_dev, 3) if avg_dev is not None else None,
        "latest_observation_period": latest.get("actual_observation_period", ""),
        "latest_summary": latest.get("summary", ""),
        "risk_level": risk_level,
    }


def build_revision_logs(entries: List[dict]) -> List[dict]:
    grouped: Dict[Tuple[str, str], List[dict]] = {}
    for entry in entries:
        grouped.setdefault(_group_key(entry), [])
        grouped[_group_key(entry)].append(entry)

    revision_logs = []

    for (target_period, metric_name), group_entries in grouped.items():
        sorted_entries = sorted(
            group_entries,
            key=lambda x: (
                period_sort_tuple(x.get("actual_observation_period", "")),
                x.get("generated_at", ""),
            )
        )

        if len(sorted_entries) < 2:
            continue

        for prev, curr in zip(sorted_entries[:-1], sorted_entries[1:]):
            prev_score = prev.get("prediction_match_score", 0)
            curr_score = curr.get("prediction_match_score", 0)

            prev_dev = prev.get("deviation_pct")
            curr_dev = curr.get("deviation_pct")

            if prev_dev is not None:
                prev_dev_display = prev_dev * 100
            else:
                prev_dev_display = None

            if curr_dev is not None:
                curr_dev_display = curr_dev * 100
            else:
                curr_dev_display = None

            change_direction = "稳定"
            if curr_score > prev_score:
                change_direction = "改善"
            elif curr_score < prev_score:
                change_direction = "恶化"

            deviation_change_pct = None
            if prev_dev is not None and curr_dev is not None:
                deviation_change_pct = (curr_dev - prev_dev) * 100

            revision_logs.append({
                "forecast_target_period": target_period,
                "metric_name": metric_name,
                "from_actual_observation_period": prev.get("actual_observation_period", ""),
                "to_actual_observation_period": curr.get("actual_observation_period", ""),
                "from_match_level": prev.get("prediction_match_level", "信息不足"),
                "to_match_level": curr.get("prediction_match_level", "信息不足"),
                "from_match_score": prev_score,
                "to_match_score": curr_score,
                "from_deviation_pct": prev_dev_display,
                "to_deviation_pct": curr_dev_display,
                "deviation_change_pct": deviation_change_pct,
                "from_updated_recommendation": prev.get("updated_recommendation", ""),
                "to_updated_recommendation": curr.get("updated_recommendation", ""),
                "change_direction": change_direction,
                "revision_summary": _build_revision_summary(prev, curr, change_direction, deviation_change_pct),
            })

    revision_logs.sort(
        key=lambda x: (
            x.get("forecast_target_period", ""),
            x.get("metric_name", ""),
            period_sort_tuple(x.get("to_actual_observation_period", "")),
        )
    )
    return revision_logs


def _build_revision_summary(prev: dict, curr: dict, direction: str, deviation_change_pct: Optional[float]) -> str:
    metric_name = curr.get("metric_name", "") or "该指标"
    target = curr.get("forecast_target_period", "") or "目标期"
    from_p = prev.get("actual_observation_period", "")
    to_p = curr.get("actual_observation_period", "")
    from_lvl = prev.get("prediction_match_level", "信息不足")
    to_lvl = curr.get("prediction_match_level", "信息不足")

    parts = [
        f"{metric_name} 针对 {target} 的回测，从 {from_p} 到 {to_p} 的判断由“{from_lvl}”变为“{to_lvl}”。"
    ]

    if direction == "改善":
        parts.append("整体表现较上一观察期改善。")
    elif direction == "恶化":
        parts.append("整体表现较上一观察期恶化。")
    else:
        parts.append("整体判断未见明显方向性变化。")

    if deviation_change_pct is not None:
        if deviation_change_pct > 0:
            parts.append(f"偏差扩大 {round(abs(deviation_change_pct), 2)} 个百分点。")
        elif deviation_change_pct < 0:
            parts.append(f"偏差收敛 {round(abs(deviation_change_pct), 2)} 个百分点。")
        else:
            parts.append("偏差幅度基本不变。")

    prev_rec = prev.get("updated_recommendation", "")
    curr_rec = curr.get("updated_recommendation", "")
    if prev_rec != curr_rec and curr_rec:
        parts.append(f"建议口径由“{prev_rec}”调整为“{curr_rec}”。")

    return "".join(parts)


def rebuild_history_memory_with_backtest(company_folder: str | Path) -> dict:
    company_folder = Path(company_folder)
    history_path = Path(build_history_memory_path(company_folder))
    if history_path.exists():
        history_memory = _safe_load_json(history_path)
    else:
        history_memory = {}

    entries = load_all_forecast_check_entries(company_folder)
    revision_logs = build_revision_logs(entries)

    target_grouped: Dict[str, List[dict]] = {}
    for entry in entries:
        target = entry.get("forecast_target_period", "") or "UNKNOWN_TARGET"
        target_grouped.setdefault(target, [])
        target_grouped[target].append(entry)

    target_period_summaries = [
        _summarize_target_group(group_entries)
        for _, group_entries in sorted(target_grouped.items(), key=lambda x: x[0])
    ]

    latest_backtest_entry = entries[-1] if entries else {}
    latest_revision = revision_logs[-1] if revision_logs else {}

    history_memory["schema_version"] = SCHEMA_VERSION
    history_memory["generated_at"] = now_iso()
    history_memory["company_name"] = company_folder.name
    history_memory.setdefault("backtest_memory", {})
    history_memory["backtest_memory"]["entries"] = entries
    history_memory["backtest_memory"]["entry_count"] = len(entries)
    history_memory["backtest_memory"]["latest_entry"] = latest_backtest_entry
    history_memory["backtest_memory"]["target_period_summaries"] = target_period_summaries
    history_memory["backtest_memory"]["latest_revision"] = latest_revision
    history_memory["backtest_memory"]["revision_count"] = len(revision_logs)

    save_json_file(history_memory, history_path)

    revision_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "revision_count": len(revision_logs),
        "revisions": revision_logs,
    }
    save_json_file(revision_payload, _revision_log_path(company_folder))

    return {
        "status": "ok",
        "history_memory_path": str(history_path),
        "revision_log_path": str(_revision_log_path(company_folder)),
        "entry_count": len(entries),
        "revision_count": len(revision_logs),
        "latest_entry": latest_backtest_entry,
        "latest_revision": latest_revision,
        "target_period_summaries": target_period_summaries,
    }


def load_revision_log(company_folder: str | Path) -> dict:
    path = _revision_log_path(company_folder)
    if path.exists():
        return _safe_load_json(path)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",
        "company_name": Path(company_folder).name,
        "revision_count": 0,
        "revisions": [],
    }