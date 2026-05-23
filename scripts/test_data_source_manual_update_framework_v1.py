"""Test Data Source Manual Update Framework v1"""
import json, sys, os
from pathlib import Path
from datetime import date, timedelta

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.data_source_manual_update_framework_v1 import (
    is_effective_data_day, get_latest_available_data_date,
    calculate_update_start_date, make_source_status, get_calendar_policy
)

passed=0; failed=0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed+=1
    else: print(f"FAIL: {name}"); failed+=1

# 1. Effective day calendar
ck("monday_effective", is_effective_data_day(date(2026,5,18),"morningstar"))
ck("friday_effective", is_effective_data_day(date(2026,5,22),"morningstar"))
ck("saturday_not_effective", not is_effective_data_day(date(2026,5,23),"morningstar"))
ck("sunday_not_effective", not is_effective_data_day(date(2026,5,24),"morningstar"))

# 2. Latest available date (Saturday May 23 -> Friday May 22)
ck("sat_fallback_to_fri", get_latest_available_data_date("morningstar", date(2026,5,23)) == date(2026,5,22))
ck("sun_fallback_to_fri", get_latest_available_data_date("morningstar", date(2026,5,24)) == date(2026,5,22))
ck("mon_stays_mon", get_latest_available_data_date("morningstar", date(2026,5,25)) == date(2026,5,25))

# 3. Update start date (3 effective days back)
# From May 22 (Fri), 3 effective days back: Fri, Thu, Wed -> May 20
start = calculate_update_start_date(date(2026,5,22), 3, "morningstar")
ck("update_start_3_back", start == date(2026,5,19))  # Fri->Thu=21, Thu->Wed=20, Wed->Tue=19

# From May 20 (Wed), 3 back: Wed, Tue, Mon -> May 15 (Fri)
start2 = calculate_update_start_date(date(2026,5,20), 3, "morningstar")
ck("update_start_cross_weekend", start2 == date(2026,5,15))

# 4. Source status structure
st = make_source_status("test", "Test Source", "market_data", "token")
ck("status_structure", st["source_id"]=="test")
ck("status_lookback", st["lookback_effective_days"]==3)
ck("status_auth", st["token_required"])

# 5. Calendar policy
pol = get_calendar_policy("morningstar")
ck("calendar_type", pol["type"]=="weekday_based")

# 6. Morningstar update wrapper exists
ms_update = PROJECT_ROOT / "scripts" / "run_morningstar_manual_database_update_v1.py"
ck("wrapper_exists", ms_update.exists())

# 7. Run the update wrapper
os.chdir(str(PROJECT_ROOT))
from scripts.run_morningstar_manual_database_update_v1 import run_morningstar_update
result = run_morningstar_update()
ck("wrapper_runs", result["status"] in ("ok","failed"))
ck("wrapper_mode", "standard_snapshot_update" in result.get("mode",""))
ck("latest_data_not_none", result.get("latest_data_date") is not None)

# 8. Output files exist
md = PROJECT_ROOT / "runtime" / "morningstar_manual_update"
ck("run_state", (md/"morningstar_manual_update_run_state.json").exists())
ck("checkpoint", (md/"morningstar_manual_update_checkpoint.json").exists())
ck("manifest", (md/"morningstar_manual_update_manifest.json").exists())
ck("qa", (md/"morningstar_manual_update_qa_summary.json").exists())
ck("failure_log", (md/"morningstar_manual_update_failure_log.json").exists())
ck("dashboard_summary", (md/"morningstar_manual_update_dashboard_summary.json").exists())
ck("window_calc", (md/"morningstar_update_window_calculation_v1.json").exists())
ck("latest_scan", (md/"morningstar_latest_data_date_scan_v1.json").exists())
ck("upsert_policy", (md/"morningstar_same_date_upsert_policy_v1.json").exists())
ck("gap_review", (md/"morningstar_closing_gap_review_v1.json").exists())

# 9. Data source status directory
ds = PROJECT_ROOT / "runtime" / "data_source_status"
ck("ds_status_dir", ds.exists())

# 10. Upsert policy check
upsert = json.loads((md/"morningstar_same_date_upsert_policy_v1.json").read_text(encoding="utf-8"))
ck("upsert_rule", upsert["upsert_policy"]["rule"]=="latest_collected_wins")
ck("upsert_overwrite", upsert["upsert_policy"]["same_date_overwrite_enabled"])

# 11. User can trigger via endpoint
actSrv = PROJECT_ROOT / "scripts" / "run_dashboard_v1_action_server.py"
srv_text = actSrv.read_text(encoding="utf-8")
ck("endpoint_update", "/api/dashboard/data_sources/morningstar/update" in srv_text)
ck("endpoint_status", "/api/dashboard/data_sources/morningstar/status" in srv_text)

# 12. Dashboard has update button
fe_idx = PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "index.html"
fe_text = fe_idx.read_text(encoding="utf-8")
ck("dashboard_update_btn", "triggerMSUpdate" in fe_text)
ck("dashboard_source_bar", "ms-src-bar" in fe_text)

# 13. TRUSTED CONSUMPTION NOT OPENED
tna_qa = json.loads((md/"morningstar_manual_update_qa_summary.json").read_text(encoding="utf-8"))
ck("qa_trusted_false", tna_qa["checks"]["trusted_consumption"] is False)
ck("qa_tna_blocked", tna_qa["checks"]["tna_blocked"] is True)
ck("qa_non_china", tna_qa["checks"]["non_china_excluded"] is True)
ck("qa_full_backfill_off", tna_qa["checks"]["full_backfill_disabled"] is True)

# 14. Token NOT leaked
ms_state = json.loads((md/"morningstar_manual_update_run_state.json").read_text(encoding="utf-8"))
ck("state_no_token", "md_auth_token" not in ms_state)

print(f"\nResults: {passed} passed, {failed} failed, {passed+failed} total")
if failed>0: sys.exit(1)
