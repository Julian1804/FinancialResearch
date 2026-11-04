"""Small, reusable boundary for diagnostics that may cross trust boundaries.

This module deliberately knows nothing about financial semantics.  It only
removes credential-like material and machine-specific paths from values before
they are emitted as API details or log payloads.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REDACTED = "<REDACTED>"
LOCAL_PATH = "<LOCAL_PATH>"
_MAX_TEXT_LENGTH = 2_000

_SENSITIVE_NAMES = {
    "access_token", "api_key", "appkey", "auth", "authorization", "client_secret",
    "cookie", "credential", "csrftoken", "md_auth_token", "password", "passwd",
    "private_key", "refresh_token", "secret", "session", "sessionid", "signature",
    "sig", "token",
}
_SENSITIVE_ASSIGNMENT = re.compile(
    r"((?<![A-Za-z0-9])(?:access[_-]?token|api[_-]?key|appkey|auth|authorization|"
    r"client[_-]?secret|cookie|credential|csrf(?:token)?|md[_-]?auth[_-]?token|"
    r"password|passwd|private[_-]?key|refresh[_-]?token|secret|session(?:id)?|"
    r"signature|sig|token)(?![A-Za-z0-9])\s*[:=]\s*)"
    r"([^&\s,;)}\]]+)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?<![-\w])\b(Bearer|Basic)\s+[A-Za-z0-9+/=._~-]+", re.IGNORECASE)
_EMBEDDED_URL_CREDENTIAL = re.compile(r"(https?://)([^/\s:@]+(?::[^/\s@]*)?@)", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"(?i)(?<![\w])(?:[A-Z]:\\|\\\\)[^<>\r\n\"']+")
_POSIX_PATH = re.compile(r"(?<![\w])/(?:Users|home|tmp|var|opt|mnt|workspace)/[^\s,;)}\]]+")


def redact_text(value: Any) -> str:
    """Return bounded text safe for logs, API diagnostics, and error envelopes."""

    text = str(value)
    text = _BEARER.sub(lambda match: f"{match.group(1)} {REDACTED}", text)
    text = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{REDACTED}", text)
    text = _EMBEDDED_URL_CREDENTIAL.sub(lambda match: f"{match.group(1)}{REDACTED}@", text)
    text = _WINDOWS_PATH.sub(LOCAL_PATH, text)
    text = _POSIX_PATH.sub(LOCAL_PATH, text)
    if len(text) > _MAX_TEXT_LENGTH:
        text = text[:_MAX_TEXT_LENGTH] + "..."
    return text


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize mappings and collections without losing structure."""

    if key is not None and _is_sensitive_key(str(key)):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(item_key): redact_value(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(value)


def _is_sensitive_key(key: str) -> bool:
    """Recognize credential names without matching ordinary words such as authority."""

    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    parts = [part for part in re.split(r"[^a-z0-9]+", normalized) if part]
    compact = "".join(parts)
    return normalized in _SENSITIVE_NAMES or compact in _SENSITIVE_NAMES or any(
        part in _SENSITIVE_NAMES for part in parts
    )


def safe_exception_message(exc: BaseException | Any) -> str:
    """Sanitize an exception while retaining its useful operational context."""

    return redact_text(getattr(exc, "message", None) or str(exc))
