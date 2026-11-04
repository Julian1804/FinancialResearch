from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from backend.app.core.config import PROJECT_ROOT


SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
EXPECTED_SECRET_SECTION = "morningstar"
EXPECTED_TOKEN_FIELD = "md_auth_token"
TOKEN_EXPIRES_HOURS = 24
EXPIRING_SOON_HOURS = 2
VALIDATION_TIMEOUT_SECONDS = 20
VALIDATION_CALLABLE = "md.direct.get_morningstar_data_sets"

ValidationKind = Literal["valid", "invalid", "dependency_failure", "unsupported_callable", "provider_failure"]


@dataclass(frozen=True)
class ValidationResult:
    kind: ValidationKind
    status: str
    safe_message: str


class CredentialUpdateInProgress(RuntimeError):
    pass


class SafePersistenceError(RuntimeError):
    pass


_UPDATE_LOCK = threading.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def secrets_path() -> Path:
    override = os.getenv("FR_LOCALAPP_SECRET_PATH", "").strip()
    return Path(override) if override else SECRETS_PATH


def selected_morningstar_python() -> Path:
    override = os.getenv("FR_MORNINGSTAR_PYTHON", "").strip()
    return Path(override) if override else Path(sys.executable)


def load_secret_file(path: Path | None = None) -> dict[str, Any]:
    path = path or secrets_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("local_secrets_must_be_json_object")
    return data


def mask_token(token: str | None) -> str | None:
    if not token:
        return None
    suffix = token[-4:] if len(token) >= 4 else token
    return f"****{suffix}"


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        value = json.loads(decoded)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def safe_jwt_expiry(token: str | None) -> str | None:
    if not token:
        return None
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp") if payload else None
    if not isinstance(exp, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(exp), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return None


def _jwt_expiry_dt(token: str | None) -> datetime | None:
    expiry = safe_jwt_expiry(token)
    return _parse_dt(expiry) if expiry else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_status(path: Path | None = None) -> dict[str, Any]:
    path = path or secrets_path()
    secrets = load_secret_file(path)
    ms = secrets.get(EXPECTED_SECRET_SECTION, {})
    if not isinstance(ms, dict):
        ms = {}
    token = str(ms.get(EXPECTED_TOKEN_FIELD) or "")
    saved_at = str(ms.get("token_saved_at") or "")
    saved_dt = _parse_dt(saved_at)
    expires_hours = ms.get("token_expires_hours", TOKEN_EXPIRES_HOURS)
    try:
        expires_hours_i = int(expires_hours)
    except (TypeError, ValueError):
        expires_hours_i = TOKEN_EXPIRES_HOURS

    jwt_expires_dt = _jwt_expiry_dt(token)
    expires_at = None
    remaining_seconds = None
    expiring_soon = False
    expired_estimated = False
    if jwt_expires_dt:
        expires_at = jwt_expires_dt.isoformat().replace("+00:00", "Z")
        remaining_seconds = int((jwt_expires_dt - utc_now()).total_seconds())
        expired_estimated = remaining_seconds <= 0
        expiring_soon = 0 < remaining_seconds <= EXPIRING_SOON_HOURS * 3600
    elif saved_dt:
        expires_dt = saved_dt + timedelta(hours=expires_hours_i)
        expires_at = expires_dt.isoformat().replace("+00:00", "Z")
        remaining_seconds = int((expires_dt - utc_now()).total_seconds())
        expired_estimated = remaining_seconds <= 0
        expiring_soon = 0 < remaining_seconds <= EXPIRING_SOON_HOURS * 3600

    validation_status = str(ms.get("last_validation_status") or "")
    if not token:
        status = "unconfigured"
    elif validation_status == "invalid":
        status = "validation_failed"
    elif expired_estimated:
        status = "expired"
    elif expiring_soon:
        status = "expiring_soon"
    else:
        status = "configured"

    return {
        "configured": bool(token),
        "status": status,
        "masked_token": mask_token(token),
        "token_saved_at": saved_at or None,
        "estimated_expires_at": expires_at,
        "jwt_expires_at": jwt_expires_dt.isoformat().replace("+00:00", "Z") if jwt_expires_dt else None,
        "remaining_seconds": max(0, remaining_seconds) if remaining_seconds is not None else None,
        "expiring_soon": expiring_soon,
        "expired": expired_estimated,
        "last_update_time": str(ms.get("last_update_time") or saved_at or "") or None,
        "last_validation_status": validation_status or None,
        "last_validation_time": str(ms.get("last_validation_time") or "") or None,
        "account_hint_present": bool(ms.get("account_hint")),
        "credential_capability": morningstar_validation_capability(),
    }


def _token_has_expired_exp_claim(token: str) -> bool:
    payload = _decode_jwt_payload(token)
    exp = payload.get("exp") if payload else None
    if not isinstance(exp, (int, float)):
        return False
    return datetime.fromtimestamp(float(exp), tz=timezone.utc) <= utc_now()


def _classify_child_failure(payload: dict[str, Any], returncode: int) -> ValidationResult:
    code = str(payload.get("code") or "").strip()
    if code == "dependency_unavailable":
        return ValidationResult("dependency_failure", "dependency_unavailable", "dependency unavailable")
    if code == "unsupported_callable":
        return ValidationResult("unsupported_callable", "unsupported_callable", "unsupported callable")
    message = f"{payload.get('error_type', '')} {payload.get('message', '')}".lower()
    if any(marker in message for marker in ("401", "403", "unauthorized", "forbidden", "invalid token", "expired", "auth")):
        return ValidationResult("invalid", "invalid_token", "invalid token")
    if returncode == 0:
        return ValidationResult("valid", "validated", "validated")
    return ValidationResult("provider_failure", "provider_failure", "provider failure")


def _run_morningstar_child(token: str | None = None, call_provider: bool = False) -> tuple[int, dict[str, Any]]:
    child_code = r"""
import json
import os
import sys
try:
    import morningstar_data as md
except Exception:
    print(json.dumps({"status": "failed", "code": "dependency_unavailable"}))
    sys.exit(3)
direct = getattr(md, "direct", None)
callable_obj = getattr(direct, "get_morningstar_data_sets", None) if direct is not None else None
if not callable(callable_obj):
    print(json.dumps({"status": "failed", "code": "unsupported_callable", "version": getattr(md, "__version__", None)}))
    sys.exit(4)
if os.environ.get("FR_MORNINGSTAR_CALL_PROVIDER") != "1":
    print(json.dumps({"status": "ready", "version": getattr(md, "__version__", None), "callable": "md.direct.get_morningstar_data_sets"}))
    sys.exit(0)
try:
    data = callable_obj()
    row_count = int(getattr(data, "shape", [0])[0]) if hasattr(data, "shape") else (len(data) if hasattr(data, "__len__") else None)
    print(json.dumps({"status": "success", "row_count": row_count, "version": getattr(md, "__version__", None), "callable": "md.direct.get_morningstar_data_sets"}))
except Exception as exc:
    print(json.dumps({"status": "failed", "error_type": type(exc).__name__, "message": str(exc)[:300], "version": getattr(md, "__version__", None)}))
    sys.exit(2)
"""
    env = os.environ.copy()
    if token is not None:
        env["MD_AUTH_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    env["FR_MORNINGSTAR_CALL_PROVIDER"] = "1" if call_provider else "0"
    try:
        proc = subprocess.run(
            [str(selected_morningstar_python()), "-c", child_code],
            cwd=PROJECT_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VALIDATION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, {"status": "failed", "code": "provider_timeout"}
    except OSError:
        return 127, {"status": "failed", "code": "dependency_unavailable"}
    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "{}"
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = {"status": "failed", "code": "provider_failure"}
    return proc.returncode, payload if isinstance(payload, dict) else {}


def morningstar_validation_capability() -> dict[str, Any]:
    selected = selected_morningstar_python()
    if not selected.exists():
        return {
            "status": "dependency_unavailable",
            "operational": False,
            "python_environment": "missing",
            "package_available": False,
            "package_version": None,
            "validation_callable": VALIDATION_CALLABLE,
            "callable_available": False,
        }
    if selected == Path(sys.executable):
        spec = importlib.util.find_spec("morningstar_data")
        local_importable = spec is not None
    else:
        local_importable = None
    returncode, payload = _run_morningstar_child(call_provider=False)
    package_available = payload.get("status") in {"ready", "success"} or returncode not in {3, 127}
    callable_available = payload.get("callable") == VALIDATION_CALLABLE or payload.get("status") == "ready"
    status = "operational" if returncode == 0 and callable_available else str(payload.get("code") or "dependency_unavailable")
    return {
        "status": status,
        "operational": status == "operational",
        "python_environment": "configured_override" if os.getenv("FR_MORNINGSTAR_PYTHON", "").strip() else "backend_current_python",
        "backend_python_has_package": local_importable,
        "package_available": bool(package_available),
        "package_version": payload.get("version"),
        "validation_callable": VALIDATION_CALLABLE,
        "callable_available": bool(callable_available),
    }


def validate_with_morningstar_data(token: str) -> ValidationResult:
    if not token.strip():
        return ValidationResult("invalid", "empty_token", "empty token")
    fixture_mode = os.getenv("FR_MORNINGSTAR_VALIDATION_MODE", "").strip().lower()
    if fixture_mode == "fixture":
        if token in {"fixture-valid-token", "fixture-persistence-failure"} or token.startswith("fixture-valid."):
            return ValidationResult("valid", "validated", "fixture validated")
        if token == "fixture-dependency-unavailable":
            return ValidationResult("dependency_failure", "dependency_unavailable", "fixture dependency unavailable")
        if token == "fixture-unsupported-callable":
            return ValidationResult("unsupported_callable", "unsupported_callable", "fixture unsupported callable")
        if token == "fixture-provider-failure":
            return ValidationResult("provider_failure", "provider_timeout", "fixture provider timeout")
        return ValidationResult("invalid", "invalid_token", "fixture invalid")
    if _token_has_expired_exp_claim(token):
        return ValidationResult("invalid", "expired_token", "expired token")

    returncode, payload = _run_morningstar_child(token=token, call_provider=True)
    if returncode == 124:
        return ValidationResult("provider_failure", "provider_timeout", "provider timeout")
    return _classify_child_failure(payload, returncode)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd = None
    temp_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        temp_path = Path(temp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = None
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception as exc:
        if fd is not None:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise SafePersistenceError("safe_persistence_failed") from exc


def update_token(
    token: str,
    account_hint: str | None = None,
    path: Path | None = None,
    validator: Callable[[str], ValidationResult] = validate_with_morningstar_data,
) -> dict[str, Any]:
    path = path or secrets_path()
    token = token.strip()
    if not token:
        return {"status": "error", "error_type": "invalid_token", "reason": "empty_token"}

    if not _UPDATE_LOCK.acquire(blocking=False):
        return {"status": "error", "error_type": "concurrent_update", "reason": "update_in_progress"}
    try:
        before = load_secret_file(path)
        validation = validator(token)
        if validation.kind == "invalid":
            return {"status": "error", "error_type": "invalid_token", "reason": validation.status}
        if validation.kind == "dependency_failure":
            return {"status": "error", "error_type": "dependency_unavailable", "reason": validation.status}
        if validation.kind == "unsupported_callable":
            return {"status": "error", "error_type": "unsupported_callable", "reason": validation.status}
        if validation.kind == "provider_failure":
            return {"status": "error", "error_type": "provider_failure", "reason": validation.status}

        after = deepcopy(before)
        ms = after.setdefault(EXPECTED_SECRET_SECTION, {})
        if not isinstance(ms, dict):
            ms = {}
            after[EXPECTED_SECRET_SECTION] = ms
        old_hint = str(ms.get("account_hint") or "")
        now = iso_now()
        ms[EXPECTED_TOKEN_FIELD] = token
        ms["token_saved_at"] = now
        ms["last_update_time"] = now
        ms["token_expires_hours"] = TOKEN_EXPIRES_HOURS
        ms["token_source"] = "local_app_manual_input"
        ms["last_validation_status"] = validation.status
        ms["last_validation_time"] = now
        if account_hint and account_hint.strip():
            ms["account_hint"] = account_hint.strip()
        elif old_hint:
            ms["account_hint"] = old_hint
        if os.getenv("FR_MORNINGSTAR_VALIDATION_MODE", "").strip().lower() == "fixture" and token == "fixture-persistence-failure":
            raise SafePersistenceError("fixture_safe_persistence_failed")
        _atomic_write_json(path, after)
        status = build_status(path)
        status.update({"status": "ok", "validation_status": validation.status})
        return status
    except SafePersistenceError:
        return {"status": "error", "error_type": "persistence_failure", "reason": "safe_persistence_failed"}
    finally:
        _UPDATE_LOCK.release()
