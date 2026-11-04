"""Provider-neutral transport receipts and immutable byte retention.

Business owners still decide what a response means, which evidence is
authoritative, and how it is promoted.  This module owns only hashing,
receipt-shape, and atomic retain-once mechanics.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path
from typing import Any, MutableSequence

from backend.app.core.diagnostic_safety import redact_text


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def retain_bytes_once(
    root: Path,
    relative_path: Path,
    payload: bytes,
    *,
    conflict_error: type[Exception] = ValueError,
) -> Path:
    """Atomically retain bytes and reject an in-place content change."""

    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("retained response path must remain below its source root")
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if target.read_bytes() != payload:
            raise conflict_error("immutable source receipt changed in place")
        return target
    descriptor, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # The temporary file is complete before this atomic no-overwrite claim.
        # Windows rename is non-replacing; POSIX hard-link creation is likewise
        # atomic and fails if another writer claimed the target first.
        if os.name == "nt":
            os.rename(temporary, target)
        else:
            os.link(temporary, target)
            temporary_path.unlink(missing_ok=True)
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        if target.read_bytes() != payload:
            raise conflict_error("immutable source receipt changed in place")
        return target
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return target


def response_receipt(
    *,
    route: str,
    url: str,
    started: float,
    response: Any | None,
    error: BaseException | None = None,
    retained_response_file: str | None = None,
) -> dict[str, Any]:
    """Build the common operational receipt shape used by source adapters."""

    content = getattr(response, "content", b"") if response is not None else b""
    status = getattr(response, "status_code", None) if response is not None else None
    ok = bool(getattr(response, "ok", False)) if response is not None else False
    return {
        "route": route,
        "url": redact_text(url),
        "http_status": status,
        "response_bytes": len(content),
        "response_sha256": sha256_bytes(content) if response is not None else None,
        "retained_response_file": retained_response_file,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "result": "success" if error is None and response is not None and ok else "failure",
        "error": f"{type(error).__name__}: {redact_text(error)}" if error else None,
    }


def append_response_receipt(
    receipts: MutableSequence[dict[str, Any]],
    **kwargs: Any,
) -> dict[str, Any]:
    receipt = response_receipt(**kwargs)
    receipts.append(receipt)
    return receipt
