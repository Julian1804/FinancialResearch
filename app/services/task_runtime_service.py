from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from config.settings import SYSTEM_DIR

TASK_DIR = SYSTEM_DIR / "tasks"
TASK_DIR.mkdir(parents=True, exist_ok=True)

_ACTIVE_STATUSES = {"pending", "running", "cancel_requested"}
_TERMINAL_STATUSES = {"success", "failed", "cancelled"}
_LOCKS: dict[str, threading.Lock] = {}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _task_path(task_id: str) -> Path:
    return TASK_DIR / f"{task_id}.json"


def _get_lock(task_id: str) -> threading.Lock:
    if task_id not in _LOCKS:
        _LOCKS[task_id] = threading.Lock()
    return _LOCKS[task_id]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(8):
        tmp = path.parent / f"{path.stem}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_error = exc
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
    raise last_error or PermissionError(f"无法写入任务文件: {path}")


def _read_json_with_retry(path: Path) -> Optional[dict]:
    last_error = None
    for attempt in range(6):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.03 * (attempt + 1))
    if last_error:
        raise last_error
    return None


def create_task(task_type: str, company_name: str, payload: Optional[dict] = None) -> dict:
    task_id = uuid.uuid4().hex[:12]
    record = {
        "task_id": task_id,
        "task_type": task_type,
        "company_name": company_name,
        "payload": payload or {},
        "status": "pending",
        "progress": 0.0,
        "message": "等待开始",
        "error": "",
        "result": {},
        "cancel_requested": False,
        "logs": [],
        "started_at": "",
        "finished_at": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    _write_json(_task_path(task_id), record)
    return record


def get_task(task_id: str) -> Optional[dict]:
    path = _task_path(task_id)
    if not path.exists():
        return None
    try:
        return _read_json_with_retry(path)
    except Exception:
        return None


def update_task(task_id: str, **changes) -> Optional[dict]:
    lock = _get_lock(task_id)
    with lock:
        record = get_task(task_id)
        if not record:
            return None
        record.update(changes)
        record["updated_at"] = _now_iso()
        _write_json(_task_path(task_id), record)
        return record


def append_task_log(task_id: str, line: str) -> Optional[dict]:
    lock = _get_lock(task_id)
    with lock:
        record = get_task(task_id)
        if not record:
            return None
        logs = record.get("logs", [])
        logs.append(f"[{_now_iso()}] {line}")
        record["logs"] = logs[-300:]
        record["updated_at"] = _now_iso()
        _write_json(_task_path(task_id), record)
        return record


def request_cancel(task_id: str) -> Optional[dict]:
    record = update_task(task_id, cancel_requested=True, status="cancel_requested", message="已请求取消，等待当前步骤结束")
    if record:
        append_task_log(task_id, "收到取消请求")
    return record


def task_should_cancel(task_id: str) -> bool:
    record = get_task(task_id)
    return bool(record and record.get("cancel_requested"))


def is_task_active(task: Optional[dict]) -> bool:
    return bool(task and task.get("status") in _ACTIVE_STATUSES)


def is_task_terminal(task: Optional[dict]) -> bool:
    return bool(task and task.get("status") in _TERMINAL_STATUSES)


def mark_running(task_id: str, message: str = "运行中") -> Optional[dict]:
    return update_task(task_id, status="running", started_at=_now_iso(), message=message)


def mark_progress(task_id: str, progress: float, message: str) -> Optional[dict]:
    progress = max(0.0, min(1.0, float(progress)))
    return update_task(task_id, progress=progress, message=message)


def mark_success(task_id: str, result: Optional[dict] = None, message: str = "完成") -> Optional[dict]:
    return update_task(task_id, status="success", progress=1.0, result=result or {}, message=message, finished_at=_now_iso())


def mark_failed(task_id: str, error: str) -> Optional[dict]:
    return update_task(task_id, status="failed", error=error, message="执行失败", finished_at=_now_iso())


def mark_cancelled(task_id: str, message: str = "已取消") -> Optional[dict]:
    return update_task(task_id, status="cancelled", message=message, finished_at=_now_iso())


def launch_background_task(task_id: str, runner: Callable[..., Any], *args, **kwargs) -> threading.Thread:
    def _wrapped():
        try:
            mark_running(task_id)
            runner(task_id, *args, **kwargs)
        except Exception as exc:
            append_task_log(task_id, f"异常: {exc}")
            mark_failed(task_id, str(exc))

    thread = threading.Thread(target=_wrapped, daemon=True, name=f"fr-task-{task_id}")
    thread.start()
    return thread
