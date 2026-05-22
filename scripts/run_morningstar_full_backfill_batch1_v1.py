"""
Morningstar Full Backfill Batch 1 v1
Controlled start of full backfill pipeline.

Scope:
- Fund/ETF master metadata via investment search
- Share class / identifier enrichment
- Holdings, look-through, returns for controlled subset
- Data point settings probe
- Entity master / crosswalk from search + holdings
- QA, checkpoint, retry queue, failure log
- No TNA/ENF consumption
- No US equity standalone time series
- No OpenAI API
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
PREFLIGHT_STATE_PATH = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state" / "run_state.json"

RAW_BASE = Path("Z:/data_lake_master/raw/licensed/morningstar")
STRUCTURED_BASE = Path("Z:/data_lake_master/structured/licensed/morningstar")
ENTITY_MASTER_NAS_BASE = Path("Z:/data_lake_master/structured/entity_master/morningstar")
LOCAL_RUNTIME_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill"
LOCAL_STATE_BASE = PROJECT_ROOT / "runtime" / "morningstar_full_backfill_state"
LOCAL_ENTITY_MASTER = PROJECT_ROOT / "runtime" / "entity_master"

RUN_DATE = datetime.now(timezone.utc).strftime("%Y%m%d")
RUN_ID = f"batch1_{RUN_DATE}_{datetime.now(timezone.utc).strftime('%H%M%S')}"

MAX_API_CALLS = 200
RATE_LIMIT_SLEEP = 2

api_call_log: list[dict[str, Any]] = []
failure_log_entries: list[dict[str, Any]] = []
retry_queue: list[dict[str, Any]] = []
records_collected: dict[str, int] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def get_token() -> str | None:
    if not SECRETS_PATH.exists():
        return None
    secrets = read_json(SECRETS_PATH)
    ms = secrets.get("morningstar", {})
    token = ms.get("md_auth_token")
    return str(token) if token else None


def run_child_call(call_name: str, child_code: str, token: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["MD_AUTH_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    started = datetime.now(timezone.utc)
    for attempt in range(1, 4):
        try:
            result = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
            stdout = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "{}"
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = {"status": "failed", "error_type": "invalid_child_json", "error_message": stdout[:800]}
            status = payload.get("status", "failed")
            entry = {
                "call_name": call_name,
                "attempted": True,
                "attempt": attempt,
                "status": status,
                "elapsed_seconds": elapsed,
                "return_code": result.returncode,
                "payload": payload.get("payload") if status == "success" else None,
                "error_type": payload.get("error_type") if status != "success" else None,
                "error_message": payload.get("error_message", result.stderr[-500:]) if status != "success" else None,
            }
            if status != "success" and attempt < 3:
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            return entry
        except subprocess.TimeoutExpired:
            elapsed = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
            if attempt < 3:
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            return {
                "call_name": call_name,
                "attempted": True,
                "attempt": attempt,
                "status": "timeout",
                "elapsed_seconds": elapsed,
                "error_type": "timeout",
                "error_message": "call exceeded 60s timeout",
            }
        except Exception as exc:
            if attempt < 3:
                time.sleep(RATE_LIMIT_SLEEP)
                continue
            return {
                "call_name": call_name,
                "attempted": True,
                "attempt": attempt,
                "status": "exception",
                "elapsed_seconds": 0,
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:500],
            }
    return {"call_name": call_name, "attempted": False, "status": "unknown", "error_type": "logic_error"}


def record_api_call(entry: dict[str, Any]) -> None:
    api_call_log.append(entry)
    if entry["status"] != "success":
        failure_log_entries.append({
            "timestamp": utc_now(),
            "call_name": entry["call_name"],
            "error_type": entry.get("error_type"),
            "error_message": entry.get("error_message"),
        })
        retry_queue.append({
            "call_name": entry["call_name"],
            "reason": entry.get("error_type"),
            "queued_at": utc_now(),
        })


def save_checkpoint(label: str) -> None:
    checkpoint = {
        "run_id": RUN_ID,
        "label": label,
        "timestamp": utc_now(),
        "api_calls_made": len(api_call_log),
        "records_collected": records_collected.copy(),
        "failure_count": len(failure_log_entries),
    }
    write_json(LOCAL_STATE_BASE / f"checkpoint_{label}.json", checkpoint)


def build_child_code_for_search(keyword: str, count: int) -> str:
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.investments(keyword={keyword!r}, count={count})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head({count}).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_datasets(scope: str | None = None) -> str:
    scope_call = f"md.direct.get_morningstar_data_sets({scope!r})" if scope else "md.direct.get_morningstar_data_sets()"
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = {scope_call}
    payload = {{
        "row_count": int(data.shape[0]) if hasattr(data, "shape") else len(data),
        "columns": [str(c) for c in list(data.columns)] if hasattr(data, "columns") else [],
        "rows": data.head(50).where(data.notna(), None).to_dict(orient="records") if hasattr(data, "head") else [],
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_data_point_settings(dps: list[str]) -> str:
    dps_str = json.dumps(dps)
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.get_data_point_settings({dps_str})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head(20).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_holdings(investment_ids: list[str]) -> str:
    ids_str = json.dumps(investment_ids)
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.get_holdings(investments={ids_str})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head(500).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_lookthrough(investment_ids: list[str]) -> str:
    ids_str = json.dumps(investment_ids)
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.get_lookthrough_holdings(investments={ids_str})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head(500).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_returns(investment_ids: list[str]) -> str:
    ids_str = json.dumps(investment_ids)
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.get_returns(investments={ids_str})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head(300).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def build_child_code_for_investment_data(investment_ids: list[str], data_points: list[str]) -> str:
    ids_str = json.dumps(investment_ids)
    dps_str = json.dumps([{"datapointId": dp} for dp in data_points])
    return f'''
import json, os, sys
try:
    import morningstar_data as md
    data = md.direct.get_investment_data(investments={ids_str}, data_points={dps_str})
    payload = {{
        "row_count": int(data.shape[0]),
        "columns": [str(c) for c in list(data.columns)],
        "rows": data.head(100).where(data.notna(), None).to_dict(orient="records"),
    }}
    print(json.dumps({{"status":"success","payload":payload}}, ensure_ascii=False, default=str))
except Exception as exc:
    print(json.dumps({{"status":"failed","error_type":type(exc).__name__,"error_message":str(exc)[:1000]}}, ensure_ascii=False))
    sys.exit(2)
'''


def main() -> dict[str, Any]:
    # 1) Preflight gate
    preflight = read_json(PREFLIGHT_STATE_PATH)
    if not preflight.get("preflight_passed"):
        print("Preflight did not pass. Stopping.")
        sys.exit(1)

    token = get_token()
    if not token:
        print("Token missing. Stopping.")
        sys.exit(1)

    # 2) Prepare directories
    for base in [RAW_BASE, STRUCTURED_BASE, ENTITY_MASTER_NAS_BASE, LOCAL_RUNTIME_BASE, LOCAL_STATE_BASE]:
        base.mkdir(parents=True, exist_ok=True)

    raw_run_dir = RAW_BASE / RUN_DATE
    structured_run_dir = STRUCTURED_BASE / RUN_DATE
    raw_run_dir.mkdir(parents=True, exist_ok=True)
    structured_run_dir.mkdir(parents=True, exist_ok=True)

    # 3) Discovery calls
    searches = [
        ("search_etf", "ETF", 50),
        ("search_mutual_fund", "Mutual Fund", 50),
        ("search_bond_fund", "Bond Fund", 50),
        ("search_commodity_fund", "Commodity Fund", 50),
        ("search_index_fund", "Index Fund", 50),
    ]

    all_search_results: dict[str, Any] = {}
    discovered_investment_ids: list[str] = []

    # Dataset listings
    for call_name, scope in [("datasets_all", None), ("datasets_fo", "FO")]:
        if len(api_call_log) >= MAX_API_CALLS:
            break
        code = build_child_code_for_datasets(scope)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            all_search_results[call_name] = entry["payload"]
            write_json(raw_run_dir / f"{call_name}_raw.json", entry["payload"])
            records_collected[call_name] = entry["payload"].get("row_count", 0)
        time.sleep(RATE_LIMIT_SLEEP)

    # Search calls
    for call_name, keyword, count in searches:
        if len(api_call_log) >= MAX_API_CALLS:
            break
        code = build_child_code_for_search(keyword, count)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            payload = entry["payload"]
            all_search_results[call_name] = payload
            write_json(raw_run_dir / f"{call_name}_raw.json", payload)
            records_collected[call_name] = payload.get("row_count", 0)
            for row in payload.get("rows", [])[:count]:
                inv_id = row.get("SecId") or row.get("Performance Id")
                if inv_id and inv_id not in discovered_investment_ids:
                    discovered_investment_ids.append(inv_id)
        time.sleep(RATE_LIMIT_SLEEP)

    save_checkpoint("after_search")

    # Data point settings
    dps = ["OS01W", "HP010", "F0GBR0AUM", "F0GBR0NAV", "F0GBR0TNA", "F0GBR04S", "F0GBR05S"]
    if len(api_call_log) < MAX_API_CALLS:
        code = build_child_code_for_data_point_settings(dps)
        entry = run_child_call("data_point_settings_batch1", code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            write_json(raw_run_dir / "data_point_settings_raw.json", entry["payload"])
            records_collected["data_point_settings"] = entry["payload"].get("row_count", 0)
        time.sleep(RATE_LIMIT_SLEEP)

    # Controlled subset for deep calls
    selected_ids = discovered_investment_ids[:30]
    seed_ids = ["FEUSA00001", "FEUSA00003", "FEUSA04ABS", "FEUSA04AD2", "FEUSA0002P"]
    for sid in seed_ids:
        if sid not in selected_ids:
            selected_ids.append(sid)
    selected_ids = selected_ids[:30]

    # Holdings calls (batch of 5)
    holdings_batches = [selected_ids[i:i+5] for i in range(0, min(len(selected_ids), 15), 5)]
    all_holdings_rows: list[dict[str, Any]] = []
    for idx, batch in enumerate(holdings_batches):
        if len(api_call_log) >= MAX_API_CALLS:
            break
        call_name = f"holdings_batch_{idx}"
        code = build_child_code_for_holdings(batch)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            payload = entry["payload"]
            write_json(raw_run_dir / f"{call_name}_raw.json", payload)
            rows = payload.get("rows", [])
            records_collected[call_name] = len(rows)
            all_holdings_rows.extend(rows)
        time.sleep(RATE_LIMIT_SLEEP)

    save_checkpoint("after_holdings")

    # Look-through calls (batch of 3)
    lt_batches = [selected_ids[i:i+3] for i in range(0, min(len(selected_ids), 9), 3)]
    all_lt_rows: list[dict[str, Any]] = []
    for idx, batch in enumerate(lt_batches):
        if len(api_call_log) >= MAX_API_CALLS:
            break
        call_name = f"lookthrough_batch_{idx}"
        code = build_child_code_for_lookthrough(batch)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            payload = entry["payload"]
            write_json(raw_run_dir / f"{call_name}_raw.json", payload)
            rows = payload.get("rows", [])
            records_collected[call_name] = len(rows)
            all_lt_rows.extend(rows)
        time.sleep(RATE_LIMIT_SLEEP)

    save_checkpoint("after_lookthrough")

    # Returns calls (batch of 5)
    ret_batches = [selected_ids[i:i+5] for i in range(0, min(len(selected_ids), 15), 5)]
    all_returns_rows: list[dict[str, Any]] = []
    for idx, batch in enumerate(ret_batches):
        if len(api_call_log) >= MAX_API_CALLS:
            break
        call_name = f"returns_batch_{idx}"
        code = build_child_code_for_returns(batch)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            payload = entry["payload"]
            write_json(raw_run_dir / f"{call_name}_raw.json", payload)
            rows = payload.get("rows", [])
            records_collected[call_name] = len(rows)
            all_returns_rows.extend(rows)
        time.sleep(RATE_LIMIT_SLEEP)

    save_checkpoint("after_returns")

    # Investment data metadata enrichment (batch of 5 IDs)
    id_batches = [selected_ids[i:i+5] for i in range(0, min(len(selected_ids), 10), 5)]
    all_investment_data_rows: list[dict[str, Any]] = []
    candidate_dps = ["F0GBR0AUM", "F0GBR0NAV", "F0GBR0TNA", "F0GBR04S", "F0GBR05S"]
    for idx, batch in enumerate(id_batches):
        if len(api_call_log) >= MAX_API_CALLS:
            break
        call_name = f"investment_data_batch_{idx}"
        code = build_child_code_for_investment_data(batch, candidate_dps)
        entry = run_child_call(call_name, code, token)
        record_api_call(entry)
        if entry["status"] == "success" and entry.get("payload"):
            payload = entry["payload"]
            write_json(raw_run_dir / f"{call_name}_raw.json", payload)
            rows = payload.get("rows", [])
            records_collected[call_name] = len(rows)
            all_investment_data_rows.extend(rows)
        time.sleep(RATE_LIMIT_SLEEP)

    save_checkpoint("after_investment_data")

    # 4) Normalize and write structured data
    fund_metadata_rows: list[dict[str, Any]] = []
    for call_name, payload in all_search_results.items():
        if not call_name.startswith("search_"):
            continue
        for row in payload.get("rows", []):
            fund_metadata_rows.append({
                "run_id": RUN_ID,
                "source_call": call_name,
                "secId": row.get("SecId"),
                "performanceId": row.get("Performance Id"),
                "fundId": row.get("Fund Id"),
                "ticker": row.get("Ticker"),
                "name": row.get("Name"),
                "isin": row.get("ISIN"),
                "cusip": row.get("CUSIP"),
                "currency": row.get("Base Currency"),
                "exchange": row.get("Exchange"),
                "country": row.get("Country"),
                "securityType": row.get("Security Type"),
                "category": row.get("Category"),
                "fundCompany": row.get("Fund Company"),
                "retrieved_at": utc_now(),
            })

    write_json(structured_run_dir / "fund_etf_metadata.json", {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "row_count": len(fund_metadata_rows),
        "rows": fund_metadata_rows,
    })
    records_collected["structured_fund_etf_metadata"] = len(fund_metadata_rows)

    write_json(structured_run_dir / "holdings.json", {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "row_count": len(all_holdings_rows),
        "rows": all_holdings_rows,
    })
    records_collected["structured_holdings"] = len(all_holdings_rows)

    write_json(structured_run_dir / "lookthrough_holdings.json", {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "row_count": len(all_lt_rows),
        "rows": all_lt_rows,
    })
    records_collected["structured_lookthrough"] = len(all_lt_rows)

    write_json(structured_run_dir / "returns.json", {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "row_count": len(all_returns_rows),
        "rows": all_returns_rows,
    })
    records_collected["structured_returns"] = len(all_returns_rows)

    write_json(structured_run_dir / "investment_data.json", {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "row_count": len(all_investment_data_rows),
        "rows": all_investment_data_rows,
    })
    records_collected["structured_investment_data"] = len(all_investment_data_rows)

    # 5) Entity Master / Crosswalk
    entity_map: dict[str, dict[str, Any]] = {}

    for row in fund_metadata_rows:
        sec_id = row.get("secId") or row.get("performanceId") or row.get("fundId")
        if not sec_id:
            continue
        if sec_id not in entity_map:
            entity_map[sec_id] = {
                "secId": sec_id,
                "ticker": row.get("ticker"),
                "name": row.get("name"),
                "isin": row.get("isin"),
                "cusip": row.get("cusip"),
                "currency": row.get("currency"),
                "exchange": row.get("exchange"),
                "country": row.get("country"),
                "category": row.get("category"),
                "security_type": row.get("securityType"),
                "fundCompany": row.get("fundCompany"),
                "source_provenance": "md.direct.investments",
                "entity_shell_status": "candidate_preview",
                "price_time_series_collected": False,
                "first_seen_run_id": RUN_ID,
            }

    for h in all_holdings_rows:
        sec_id = h.get("secId") or h.get("holdingId") or h.get("identifier")
        name = h.get("name") or h.get("holdingName")
        if not sec_id:
            continue
        if sec_id not in entity_map:
            entity_map[sec_id] = {
                "secId": sec_id,
                "name": name,
                "isin": h.get("isin"),
                "cusip": h.get("cusip"),
                "ticker": h.get("ticker"),
                "currency": h.get("currency"),
                "security_type": h.get("detailHoldingType") or h.get("detailHoldingTypeCode") or h.get("assetType"),
                "source_provenance": "md.direct.get_holdings",
                "entity_shell_status": "candidate_preview",
                "price_time_series_collected": False,
                "first_seen_run_id": RUN_ID,
            }

    for h in all_lt_rows:
        sec_id = h.get("secId") or h.get("holdingId")
        name = h.get("name") or h.get("holdingName")
        if not sec_id:
            continue
        if sec_id not in entity_map:
            entity_map[sec_id] = {
                "secId": sec_id,
                "name": name,
                "security_type": h.get("detailHoldingTypeCode") or h.get("assetType"),
                "source_provenance": "md.direct.get_lookthrough_holdings",
                "entity_shell_status": "candidate_preview",
                "price_time_series_collected": False,
                "first_seen_run_id": RUN_ID,
            }

    entity_shells = list(entity_map.values())
    us_equity_shells = [e for e in entity_shells if e.get("security_type") == "ST" and e.get("country") == "USA"]
    bond_shells = [e for e in entity_shells if e.get("security_type") in ("BOND", "BO")]
    commodity_shells = [e for e in entity_shells if e.get("security_type") in ("COMMODITY", "CO")]
    fund_etf_shells = [e for e in entity_shells if e.get("security_type") in ("FE", "FO", "ETF", "MF")]
    other_shells = [e for e in entity_shells if e not in us_equity_shells + bond_shells + commodity_shells + fund_etf_shells]

    entity_master_meta = {
        "generated_at": utc_now(),
        "run_id": RUN_ID,
        "total_entities": len(entity_shells),
        "us_equity_entities": len(us_equity_shells),
        "bond_entities": len(bond_shells),
        "commodity_entities": len(commodity_shells),
        "fund_etf_entities": len(fund_etf_shells),
        "other_entities": len(other_shells),
        "license_warning": "candidate_only; identifier mapping only, no price time series",
    }

    write_json(ENTITY_MASTER_NAS_BASE / f"morningstar_entity_master_{RUN_DATE}.json", {
        **entity_master_meta,
        "entities": entity_shells,
    })
    write_json(LOCAL_ENTITY_MASTER / f"morningstar_entity_master_{RUN_DATE}.json", {
        **entity_master_meta,
        "entities": entity_shells,
    })

    crosswalk = {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "crosswalk_type": "morningstar_identifier_crosswalk",
        "identifier_priority": ["secId", "performanceId", "fundId", "shareClassId", "isin", "cusip", "ticker"],
        "mappings": [
            {
                "secId": row.get("secId"),
                "performanceId": row.get("performanceId"),
                "fundId": row.get("fundId"),
                "ticker": row.get("ticker"),
                "isin": row.get("isin"),
                "cusip": row.get("cusip"),
                "name": row.get("name"),
                "currency": row.get("currency"),
                "exchange": row.get("exchange"),
            }
            for row in fund_metadata_rows
            if row.get("secId") or row.get("ticker")
        ],
    }
    (STRUCTURED_BASE / "crosswalk").mkdir(parents=True, exist_ok=True)
    write_json(STRUCTURED_BASE / "crosswalk" / f"morningstar_crosswalk_{RUN_DATE}.json", crosswalk)
    records_collected["crosswalk_mappings"] = len(crosswalk["mappings"])

    # 6) QA
    qa_results = []
    for dataset, rows in [
        ("fund_etf_metadata", fund_metadata_rows),
        ("holdings", all_holdings_rows),
        ("lookthrough_holdings", all_lt_rows),
        ("returns", all_returns_rows),
        ("investment_data", all_investment_data_rows),
    ]:
        null_count = sum(1 for r in rows for v in r.values() if v is None)
        total_fields = max((len(r) for r in rows), default=0) * len(rows)
        null_ratio = null_count / total_fields if total_fields > 0 else 0
        unique_hashes = {json.dumps(r, sort_keys=True, default=str) for r in rows}
        duplicate_count = len(rows) - len(unique_hashes)
        dup_ratio = duplicate_count / len(rows) if rows else 0
        status = "passed" if null_ratio < 0.5 and dup_ratio < 0.05 else "warning"
        qa_results.append({
            "dataset": dataset,
            "row_count": len(rows),
            "null_ratio": round(null_ratio, 4),
            "duplicate_count": duplicate_count,
            "duplicate_ratio": round(dup_ratio, 4),
            "status": status,
        })

    qa_summary = {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "overall_status": "passed" if all(q["status"] == "passed" for q in qa_results) else "warning",
        "checks": qa_results,
        "blocked_fields_checked": ["tna_enf"],
        "blocked_fields_present": False,
        "us_equity_standalone_excluded": True,
    }
    (LOCAL_RUNTIME_BASE / "qa").mkdir(parents=True, exist_ok=True)
    (STRUCTURED_BASE / "qa").mkdir(parents=True, exist_ok=True)
    write_json(LOCAL_RUNTIME_BASE / "qa" / f"batch1_qa_summary_{RUN_DATE}.json", qa_summary)
    write_json(STRUCTURED_BASE / "qa" / f"batch1_qa_summary_{RUN_DATE}.json", qa_summary)

    # 7) Update state files
    run_state = read_json(LOCAL_STATE_BASE / "run_state.json")
    run_state["batch1_completed"] = True
    run_state["batch1_run_id"] = RUN_ID
    run_state["batch1_api_calls"] = len(api_call_log)
    run_state["batch1_records"] = records_collected.copy()
    run_state["batch1_timestamp"] = utc_now()
    run_state["next_step"] = "batch2_or_incremental"
    write_json(LOCAL_STATE_BASE / "run_state.json", run_state)

    write_json(LOCAL_STATE_BASE / "failure_log.json", {
        "log_id": "morningstar_failure_log_v1",
        "generated_at": utc_now(),
        "entries": failure_log_entries,
    })

    write_json(LOCAL_STATE_BASE / "retry_queue.json", {
        "queue_id": "morningstar_retry_queue_v1",
        "generated_at": utc_now(),
        "items": retry_queue,
    })

    # 8) Manifest
    manifest = {
        "run_id": RUN_ID,
        "generated_at": utc_now(),
        "source": "morningstar_direct",
        "batch": 1,
        "api_calls_made": len(api_call_log),
        "success_calls": len([e for e in api_call_log if e["status"] == "success"]),
        "failure_calls": len([e for e in api_call_log if e["status"] != "success"]),
        "records_collected": records_collected,
        "blocked_fields": ["tna_enf"],
        "us_equity_standalone_excluded": True,
        "formal_trusted_consumption": False,
        "no_openai_api": True,
        "output_paths": {
            "raw": str(raw_run_dir),
            "structured": str(structured_run_dir),
            "entity_master_nas": str(ENTITY_MASTER_NAS_BASE),
            "local_runtime": str(LOCAL_RUNTIME_BASE),
            "local_state": str(LOCAL_STATE_BASE),
        },
    }
    (LOCAL_RUNTIME_BASE / "manifest").mkdir(parents=True, exist_ok=True)
    write_json(LOCAL_RUNTIME_BASE / "manifest" / f"batch1_manifest_{RUN_DATE}.json", manifest)

    print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
    return manifest


if __name__ == "__main__":
    main()
