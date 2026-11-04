"""User-owned installation bootstrap state.

The bootstrap file is intentionally outside the selected data root.  It lets a
first-run client choose a local root before the control plane, identity state,
or published data directories are created.  It is configuration metadata, not
financial data and never participates in release identity.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import ctypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BOOTSTRAP_SCHEMA = "fr_installation_bootstrap_v1"
DEFAULT_BOOTSTRAP_DIRNAME = "FinancialResearch"
DEFAULT_BOOTSTRAP_FILENAME = "installation.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def bootstrap_path() -> Path:
    explicit = os.environ.get("FR_INSTALLATION_BOOTSTRAP_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = os.environ.get("FR_INSTALLATION_BOOTSTRAP_ROOT", "").strip()
    if root:
        return Path(root).expanduser() / DEFAULT_BOOTSTRAP_FILENAME
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / DEFAULT_BOOTSTRAP_DIRNAME / DEFAULT_BOOTSTRAP_FILENAME
    # Non-Windows test/development fallback.  A release launcher on Windows
    # always supplies LOCALAPPDATA.
    return Path.home() / ".financialresearch" / DEFAULT_BOOTSTRAP_FILENAME


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def load_installation_bootstrap() -> dict[str, Any]:
    value = _read_json(bootstrap_path())
    if value.get("schema_version") != BOOTSTRAP_SCHEMA:
        return {
            "schema_version": BOOTSTRAP_SCHEMA,
            "status": "unselected",
            "selected_data_root": None,
            "updated_at_utc": None,
        }
    selected = value.get("selected_data_root")
    if value.get("status") == "selected" and isinstance(selected, str) and selected.strip():
        value["selected_data_root"] = str(Path(selected).expanduser())
        return value
    value["status"] = "unselected"
    value["selected_data_root"] = None
    return value


def selected_data_root() -> Path | None:
    value = load_installation_bootstrap()
    selected = value.get("selected_data_root")
    return Path(selected).expanduser() if value.get("status") == "selected" and selected else None


def _is_unc(path: Path) -> bool:
    text = str(path)
    return text.startswith("\\\\") or text.startswith("//")


def _windows_volume_contract(path: Path) -> dict[str, Any]:
    if os.name != "nt":
        return {"filesystem": None, "drive_type": None, "fixed_ntfs": None}
    kernel32 = ctypes.windll.kernel32
    volume_path = ctypes.create_unicode_buffer(261)
    if not kernel32.GetVolumePathNameW(str(path), volume_path, len(volume_path)):
        raise ValueError("unable to resolve the Windows storage volume")
    filesystem = ctypes.create_unicode_buffer(261)
    if not kernel32.GetVolumeInformationW(
        volume_path.value, None, 0, None, None, None, filesystem, len(filesystem)
    ):
        raise ValueError("unable to inspect the Windows storage filesystem")
    drive_type = int(kernel32.GetDriveTypeW(volume_path.value))
    if drive_type != 3:
        raise ValueError("data root must be on a local fixed drive")
    if filesystem.value.upper() != "NTFS":
        raise ValueError("data root must be on an NTFS volume")
    normalized = str(path).casefold()
    sync_roots = [
        os.environ.get(name, "").strip()
        for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")
    ]
    if any(root and (normalized == str(Path(root).resolve(strict=False)).casefold()
                     or normalized.startswith(str(Path(root).resolve(strict=False)).casefold() + os.sep))
           for root in sync_roots):
        raise ValueError("data root cannot be inside a OneDrive-synchronized folder")
    return {"filesystem": filesystem.value, "drive_type": "fixed", "fixed_ntfs": True}


def validate_data_root(value: str | os.PathLike[str], *, create: bool = False) -> dict[str, Any]:
    """Validate a user-selected local root and report capacity without data writes.

    ``create=True`` is used only by the explicit selection action.  Validation
    itself creates no FR control/data state; the write probe is removed before
    returning.
    """
    raw = str(value).strip()
    if not raw:
        raise ValueError("data root is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError("data root must be an absolute local path")
    if _is_unc(path):
        raise ValueError("data root must be a local fixed path, not a UNC path")
    resolved = path.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise ValueError("data root exists but is not a directory")
    if create:
        resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.exists():
        raise ValueError("data root does not exist; choose an existing directory or retry with creation enabled")
    volume = _windows_volume_contract(resolved)
    try:
        usage = shutil.disk_usage(resolved)
    except OSError as exc:
        raise ValueError(f"unable to read data-root capacity: {exc}") from exc
    probe: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".fr_write_probe_", dir=resolved, delete=False) as handle:
            probe = Path(handle.name)
            handle.write(b"fr")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise ValueError(f"data root is not writable: {exc}") from exc
    finally:
        if probe is not None:
            try:
                probe.unlink()
            except OSError:
                pass
    return {
        "path": str(resolved),
        "is_local": True,
        "free_bytes": int(usage.free),
        "total_bytes": int(usage.total),
        "writable": True,
        **volume,
    }


def select_data_root(value: str | os.PathLike[str]) -> dict[str, Any]:
    info = validate_data_root(value, create=True)
    payload = {
        "schema_version": BOOTSTRAP_SCHEMA,
        "status": "selected",
        "selected_data_root": info["path"],
        "selected_at_utc": _now(),
        "updated_at_utc": _now(),
    }
    path = bootstrap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return {**payload, "capacity": info, "restart_required": True}
