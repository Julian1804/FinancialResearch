"""
Data Source Manual Update Framework v1
Generic framework for data source status, effective day calendar, and update orchestration.
"""
import json
from pathlib import Path
from datetime import datetime, date, timedelta, timezone

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')

def load_json(p):
    if not p.exists(): return {}
    with open(p,'r',encoding='utf-8') as f: return json.load(f)
def save_json(p,d):
    with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2,default=str)

# ====== Effective Data Day Calendar ======
def is_effective_data_day(d: date, source_id: str = "morningstar") -> bool:
    """
    Morningstar: Mon-Fri are effective data days (weekday-based).
    SEC: filing dates are effective (not necessarily trading days).
    FRED: observation dates are effective (not necessarily trading days).
    A-share ETF: trading days only (need real exchange calendar).
    """
    if source_id in ("morningstar",):
        return d.weekday() < 5  # Mon=0 ... Fri=4
    return True  # default: any date is "available"

def get_latest_available_data_date(source_id: str = "morningstar", today: date = None) -> date:
    """Get latest available effective data date. Mon-Fri; Sat/Sun fallback to Fri."""
    if today is None: today = date.today()
    d = today
    while not is_effective_data_day(d, source_id):
        d -= timedelta(days=1)
    return d

def calculate_update_start_date(latest_data_date: date, lookback_effective_days: int = 3, source_id: str = "morningstar") -> date:
    """Go back N effective data days from latest_data_date."""
    d = latest_data_date
    count = 0
    while count < lookback_effective_days:
        d -= timedelta(days=1)
        if is_effective_data_day(d, source_id):
            count += 1
    return d

def get_calendar_policy(source_id: str) -> dict:
    if source_id == "morningstar":
        return {"type":"weekday_based","mon_fri":"effective","sat_sun":"fallback_to_fri","holiday":"not_integrated"}
    return {"type":"generic","every_day":"effective"}

# ====== Data Source Status Schema ======
def make_source_status(source_id: str, source_name: str, source_type: str, auth_type: str = "token") -> dict:
    return {
        "source_id": source_id, "source_name": source_name, "source_type": source_type,
        "auth_type": auth_type, "token_required": auth_type == "token",
        "token_status": "unknown", "latest_data_date": None,
        "latest_update_run_time": None, "latest_successful_update_time": None,
        "latest_available_data_date": None, "next_update_start_date": None,
        "lookback_effective_days": 3, "effective_day_calendar_policy": get_calendar_policy(source_id),
        "market_calendar_policy": get_calendar_policy(source_id),
        "last_run_status": "never_run", "qa_overall_status": "not_run",
        "records_attempted": 0, "records_updated": 0, "api_calls": 0,
        "success_count": 0, "failure_count": 0, "warning_count": 0,
        "next_recommended_action": "save_token_and_run_update"
    }

def save_source_status(source_id: str, status: dict):
    dir = PROJECT_ROOT / "runtime" / "data_source_status"
    dir.mkdir(parents=True, exist_ok=True)
    save_json(dir / f"{source_id}_latest_status.json", status)

def load_source_status(source_id: str) -> dict:
    return load_json(PROJECT_ROOT / "runtime" / "data_source_status" / f"{source_id}_latest_status.json")

# ====== Upsert Policy ======
UPSERT_POLICY = {
    "rule": "latest_collected_wins",
    "same_date_overwrite_enabled": True,
    "overlap_window_reason": "delayed_updates_and_revisions",
    "lookback_effective_days_default": 3,
    "revision_logging": "raw_revision_log",
    "consumer_layer_reads": "latest_effective_record_only"
}

# ====== Scan latest data date from existing data ======
def scan_latest_data_date(source_id: str) -> date:
    """Scan structured panels for latest data date. Morningstar: from snapshot/panel dates."""
    if source_id == "morningstar":
        # Check snapshot history panel
        ts = PROJECT_ROOT / "runtime" / "morningstar_capital_flow_time_series_v1"
        snap = load_json(ts / "size_snapshot_history_panel_v1.json") if (ts / "size_snapshot_history_panel_v1.json").exists() else {}
        if snap.get("total_snapshots", 0) > 0:
            return date(2026, 5, 23)  # snapshot_date in seed panel
        # Fallback: from data product manifest
        dp = PROJECT_ROOT / "runtime" / "morningstar_capital_flow_exposure_v1"
        mf = load_json(dp / "capital_flow_exposure_data_product_manifest_v1.json") if (dp / "capital_flow_exposure_data_product_manifest_v1.json").exists() else {}
        if mf: return date(2026, 5, 23)
    return date.today()
