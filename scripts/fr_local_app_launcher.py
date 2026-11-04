from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]


def _local_port(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if not 1 <= value <= 65535:
        raise ValueError(f"{name} must be a valid TCP port")
    return value


RUNTIME = Path(os.environ.get("FINANCIAL_RESEARCH_RUNTIME_ROOT", "").strip() or ROOT / "runtime") / "local_app"
STATE_PATH = RUNTIME / "fr_local_app_state.json"
BACKEND_PORT = _local_port("FR_LOCAL_BACKEND_PORT", 8000)
FRONTEND_PORT = _local_port("FR_LOCAL_FRONTEND_PORT", 8080)
BACKEND_URL = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_URL = f"http://127.0.0.1:{FRONTEND_PORT}"
BACKEND_HEALTH = f"{BACKEND_URL}/api/health"
BACKEND_READY = f"{BACKEND_URL}/api/readiness"
FRONTEND_READY = f"{FRONTEND_URL}/index.html"
FRONTEND_BOOTSTRAP_API = f"{FRONTEND_URL}/api/workspace/bootstrap"
FRONTEND_CONFIGURATION_API = f"{FRONTEND_URL}/api/data-console/data-configuration"
FRONTEND_LIFECYCLE_API = f"{FRONTEND_URL}/api/data-console/operation-lifecycle"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def check_python_deps() -> list[str]:
    missing: list[str] = []
    for module in ("fastapi", "openpyxl", "pyarrow", "uvicorn", "numpy", "sklearn",
                   "statsmodels", "linearmodels", "arch"):
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    return missing


def fetch_text(url: str, timeout: float = 1.5) -> tuple[int | None, str]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "fr-local-launcher"}), timeout=timeout) as response:
            return response.status, response.read(5000).decode("utf-8", errors="replace")
    except Exception:
        return None, ""


def fetch_json(url: str, timeout: float = 2.5) -> tuple[int | None, dict]:
    try:
        with urlopen(Request(url, headers={"User-Agent": "fr-local-launcher"}), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            return response.status, payload if isinstance(payload, dict) else {}
    except HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return exc.code, {}
        return exc.code, payload if isinstance(payload, dict) else {}
    except Exception:
        return None, {}


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def backend_healthy() -> bool:
    status, text = fetch_text(BACKEND_HEALTH)
    return status == 200 and "financial_research_backend" in text


def backend_uses_selected_runtime() -> bool:
    status, payload = fetch_json(f"{BACKEND_URL}/api/debug/build_info")
    executable = str(payload.get("python_exe") or "")
    return bool(status == 200 and executable and
                Path(executable).resolve() == Path(sys.executable).resolve() and
                Path(str(payload.get("project_root") or "")).resolve() == ROOT.resolve())


def backend_serving_ready() -> bool:
    status, payload = fetch_json(BACKEND_READY)
    return bool(
        status == 200
        and payload.get("status") == "ready"
        and payload.get("release_id")
        and payload.get("database_generation_id")
        and set(payload.get("checks") or {}) == {"china_public_fund", "china_equity"}
    )


def backend_startup_ready() -> bool:
    status, payload = fetch_json(BACKEND_READY)
    if status == 200:
        return bool(
            payload.get("status") == "ready"
            and payload.get("release_id")
            and payload.get("database_generation_id")
            and set(payload.get("checks") or {}) == {"china_public_fund", "china_equity"}
        )
    return bool(
        status == 503
        and payload.get("status") == "not_ready"
        and payload.get("error_code") == "first_publication_pending"
        and payload.get("error_class") == "serving_state_invalid"
    )


def frontend_ready() -> bool:
    status, text = fetch_text(FRONTEND_READY)
    # Readiness belongs to the stable application shell, not a mutable product
    # title.  Requiring both markers prevents an unrelated HTTP 200 page from
    # being mistaken for FR while allowing ordinary copy/title changes.
    return bool(
        status == 200
        and 'id="workspace-shell"' in text
        and '/workspace_v1/js/main.js' in text
    )


def frontend_api_ready() -> bool:
    status, payload = fetch_json(FRONTEND_BOOTSTRAP_API)
    if status != 200 or not isinstance(payload.get("apps"), dict) or not isinstance(payload.get("dashboards"), dict):
        return False
    configuration_status, configuration = fetch_json(FRONTEND_CONFIGURATION_API)
    lifecycle_status, lifecycle = fetch_json(FRONTEND_LIFECYCLE_API)
    return bool(
        configuration_status == 200
        and configuration.get("status") in {"unconfigured", "no_universe_enabled", "configured", "authority_unset"}
        and lifecycle_status == 200
        and isinstance(lifecycle.get("serving_by_universe"), dict)
        and {"Fund", "Equity"}.issubset(lifecycle["serving_by_universe"])
    )


def application_ready() -> bool:
    return backend_healthy() and backend_uses_selected_runtime() and backend_startup_ready() and frontend_ready() and frontend_api_ready()


def process_info(pid: int) -> dict:
    script = (
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId=%d\" -ErrorAction SilentlyContinue;"
        "if($p){[pscustomobject]@{ProcessId=$p.ProcessId;CommandLine=$p.CommandLine;CreationDate=$p.CreationDate;ExecutablePath=$p.ExecutablePath}|ConvertTo-Json -Compress}"
    ) % pid
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=8)
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def command_hash(command: list[str]) -> str:
    return hashlib.sha256("\0".join(command).encode("utf-8")).hexdigest()


def verify_owned(record: dict) -> bool:
    pid = int(record.get("pid") or 0)
    if pid <= 0:
        return False
    info = process_info(pid)
    if not info:
        return False
    command_line = str(info.get("CommandLine") or "")
    expected = record.get("expected_markers") or []
    if not all(str(marker) in command_line for marker in expected):
        return False
    recorded_creation = str(record.get("process_creation_date") or "")
    current_creation = str(info.get("CreationDate") or "")
    if not recorded_creation or not current_creation:
        return False
    if recorded_creation != current_creation:
        return False
    return True


def start_process(service: str, command: list[str], log_path: Path, expected_markers: list[str]) -> dict:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("ab")
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    info = process_info(proc.pid)
    return {
        "service": service,
        "pid": proc.pid,
        "started_by_launcher": True,
        "started_at": utc_now(),
        "process_creation_date": str(info.get("CreationDate") or ""),
        "process_executable_path": str(info.get("ExecutablePath") or ""),
        "cwd": str(ROOT),
        "command_hash": command_hash(command),
        "expected_markers": expected_markers,
        "log_path": str(log_path),
    }


def wait_until(name: str, predicate, timeout_seconds: int = 35) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.5)
    return False


def stop_records(records: list[dict]) -> list[dict]:
    stopped = []
    for record in records:
        if not record.get("started_by_launcher"):
            stopped.append({"service": record.get("service"), "action": "skip_reused"})
            continue
        if not verify_owned(record):
            stopped.append({"service": record.get("service"), "pid": record.get("pid"), "action": "skip_unverified"})
            continue
        pid = int(record["pid"])
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"], capture_output=True, text=True, timeout=10)
        stopped.append({"service": record.get("service"), "pid": pid, "action": "stopped"})
    return stopped


def start(open_browser: bool = True) -> int:
    if sys.version_info[:2] != (3, 13) or sys.maxsize <= 2**32:
        print("FR requires the supported CPython 3.13 x64 runtime.")
        return 2
    missing = check_python_deps()
    if missing:
        print("Missing Python dependencies: " + ", ".join(missing))
        print("Install from requirements.txt; the launcher does not install or upgrade dependencies.")
        return 2

    RUNTIME.mkdir(parents=True, exist_ok=True)
    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    records: list[dict] = []
    previous_records = {
        str(record.get("service")): record
        for record in (read_json(STATE_PATH).get("records") or [])
        if isinstance(record, dict)
    }

    def reused_record(service: str, url: str) -> dict:
        previous = previous_records.get(service)
        if previous and previous.get("started_by_launcher") and verify_owned(previous):
            retained = dict(previous)
            retained["reused_from_previous_state"] = True
            return retained
        return {"service": service, "started_by_launcher": False, "url": url}

    if backend_healthy() and not backend_uses_selected_runtime():
        print(f"Port {BACKEND_PORT} is occupied by an FR backend using a different runtime. Stop that process before supported startup.")
        return 3
    if backend_healthy():
        records.append(reused_record("backend", BACKEND_URL))
    elif port_open(BACKEND_PORT):
        print(f"Port {BACKEND_PORT} is occupied by a non-FR backend. No services started.")
        return 3
    else:
        cmd = [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)]
        records.append(start_process("backend", cmd, RUNTIME / "backend.log", ["uvicorn", "backend.app.main:app", "127.0.0.1", str(BACKEND_PORT)]))

    if frontend_ready():
        records.append(reused_record("frontend", FRONTEND_URL))
    elif port_open(FRONTEND_PORT):
        print(f"Port {FRONTEND_PORT} is occupied by a non-FR frontend. Cleaning up this attempt.")
        stop_records([r for r in records if r.get("started_by_launcher")])
        return 4
    else:
        cmd = [
            sys.executable, "scripts/fr_local_frontend_gateway.py", "--host", "127.0.0.1",
            "--port", str(FRONTEND_PORT), "--backend-origin", BACKEND_URL,
        ]
        records.append(start_process("frontend", cmd, RUNTIME / "frontend.log", ["fr_local_frontend_gateway.py", "127.0.0.1", str(FRONTEND_PORT)]))

    if not wait_until("backend", lambda: backend_healthy() and backend_uses_selected_runtime()):
        print("Backend did not become ready. Cleaning up this attempt.")
        stop_records([r for r in records if r.get("started_by_launcher")])
        return 5
    if not wait_until("backend_startup", backend_startup_ready):
        print("Backend started but platform/serving startup state is unavailable. Cleaning up this attempt.")
        stop_records([r for r in records if r.get("started_by_launcher")])
        return 8
    if not wait_until("frontend", frontend_ready):
        print("Frontend did not become ready. Cleaning up this attempt.")
        stop_records([r for r in records if r.get("started_by_launcher")])
        return 6
    if not wait_until("frontend_api", frontend_api_ready):
        print("Frontend API proxy did not become ready. Cleaning up this attempt.")
        stop_records([r for r in records if r.get("started_by_launcher")])
        return 7

    state = {
        "schema_version": "fr_local_app_launcher_state_v1",
        "attempt_id": attempt_id,
        "updated_at": utc_now(),
        "root": str(ROOT),
        "backend_url": BACKEND_URL,
        "frontend_url": FRONTEND_URL,
        "readiness_checks": {
            "backend_health": BACKEND_HEALTH,
            "backend_startup": BACKEND_READY,
            "backend_v1_serving": BACKEND_READY,
            "frontend_html": FRONTEND_READY,
            "frontend_representative_api": FRONTEND_BOOTSTRAP_API,
            "frontend_configuration": FRONTEND_CONFIGURATION_API,
            "frontend_lifecycle": FRONTEND_LIFECYCLE_API,
        },
        "records": records,
        "logs": [str(RUNTIME / "backend.log"), str(RUNTIME / "frontend.log")],
    }
    write_json(STATE_PATH, state)
    if open_browser:
        webbrowser.open(FRONTEND_URL)
    print(f"FinancialResearch local app is ready: {FRONTEND_URL}")
    print(f"Backend: {BACKEND_URL}")
    print(f"Logs: {RUNTIME}")
    print("Stop with: stop_fr_local.cmd")
    return 0


def stop() -> int:
    state = read_json(STATE_PATH)
    records = state.get("records") if isinstance(state.get("records"), list) else []
    results = stop_records(records)
    write_json(RUNTIME / "last_stop_result.json", {"schema_version": "fr_local_app_stop_result_v1", "stopped_at": utc_now(), "results": results})
    print(json.dumps({"results": results}, sort_keys=True))
    return 0


def status() -> int:
    print(json.dumps({"backend_healthy": backend_healthy(), "backend_runtime_matches": backend_uses_selected_runtime(), "backend_startup_ready": backend_startup_ready(), "backend_serving_ready": backend_serving_ready(), "frontend_ready": frontend_ready(), "frontend_api_ready": frontend_api_ready(), "application_ready": application_ready(), "state_exists": STATE_PATH.exists()}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.command == "start":
        return start(open_browser=not args.no_browser)
    if args.command == "stop":
        return stop()
    if args.command == "status":
        return status()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
