from __future__ import annotations

import json
from typing import Any

import requests

from backend.app.core.config import PARSE_LAB_BASE_URL


class ParseLabClientError(RuntimeError):
    """Raised when the Parse Lab API cannot be reached or returns an error."""


class ParseLabClient:
    """HTTP-only client for Parse Lab API v1.

    This client never imports Parse Lab internals and never calls parser binaries.
    """

    def __init__(self, base_url: str = PARSE_LAB_BASE_URL, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get_health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def list_tasks(self, limit: int = 100) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/parse/tasks?limit={limit}")

    def submit_document_parse(
        self,
        pdf_path: str,
        profile: str = "financial_report_v1_1",
        output_root: str | None = None,
        use_docling: bool = False,
        enable_visual_table_route: bool = True,
        enable_cross_page_table_detection: bool = True,
        enable_open_source_enhancers: bool = True,
        max_pages: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "pdf_path": pdf_path,
            "profile": profile,
            "use_docling": use_docling,
            "enable_visual_table_route": enable_visual_table_route,
            "enable_cross_page_table_detection": enable_cross_page_table_detection,
            "enable_open_source_enhancers": enable_open_source_enhancers,
            "max_pages": max_pages,
        }
        if output_root:
            payload["output_root"] = output_root
        return self._request("POST", "/api/v1/parse/document", json_payload=payload)

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/parse/tasks/{task_id}")

    def get_task_result(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/parse/tasks/{task_id}/result")

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/v1/parse/tasks/{task_id}/cancel")

    def delete_task(self, task_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/api/v1/parse/tasks/{task_id}")

    def _request(self, method: str, path: str, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method=method,
                url=url,
                json=json_payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ParseLabClientError(f"Parse Lab request failed: {method} {url}: {exc}") from exc

        if not response.text:
            return {}
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ParseLabClientError(f"Parse Lab returned non-JSON response: {response.text[:500]}") from exc
