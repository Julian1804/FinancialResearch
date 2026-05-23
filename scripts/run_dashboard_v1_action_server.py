from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_dashboard_v1 import (  # noqa: E402
    FRONTEND_ROOT,
    RUNTIME_ROOT,
    classify_and_save_uploaded_report,
    dashboard_summary,
    generate_dashboard_artifacts,
    read_json,
    research_workspace_summary,
    run_dashboard_v1,
    write_json,
)


class DashboardActionHandler(BaseHTTPRequestHandler):
    server_version = "FRDashboardV1ActionServer/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/dashboard/summary":
            self.send_json(dashboard_summary())
            return
        if parsed.path == "/api/dashboard/research_workspace":
            self.send_json(research_workspace_summary())
            return
        if parsed.path == "/api/dashboard/report_paths":
            self.send_json(read_json(RUNTIME_ROOT / "dashboard_v1_summary.json").get("outputs", {}))
            return
        if parsed.path == "/api/dashboard/download":
            self.serve_download(parsed.query)
            return
        if parsed.path == "/api/dashboard/morningstar/token_status":
            self._handle_token_status()
            return
        if parsed.path == "/api/dashboard/data_sources/morningstar/status":
            self._handle_morningstar_source_status()
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        payload = self.read_json_body()
        if parsed.path in {"/api/dashboard/generate_asof_snapshot", "/api/dashboard/generate_statistical_report"}:
            request = payload.get("request") or {}
            artifact_name = payload.get("artifact_name") or "ui_action_generated"
            result = generate_dashboard_artifacts(request, artifact_name)
            self.send_json(
                {
                    "status": "ok",
                    "action": "generate_asof_snapshot_and_statistical_report",
                    "outputs": {
                        "snapshot_manifest": result["snapshot"]["snapshot_manifest"]["paths"]["snapshot_manifest"],
                        "included_items": result["snapshot"]["snapshot_manifest"]["paths"]["included_items"],
                        "missing_publish_date_review": result["snapshot"]["snapshot_manifest"]["paths"]["missing_publish_date_review"],
                        "excluded_due_to_future_publish_date": result["snapshot"]["snapshot_manifest"]["paths"]["excluded_due_to_future_publish_date"],
                        "statistical_report_json": result["statistical_report"]["statistical_report_json"],
                        "statistical_report_md": result["statistical_report"]["statistical_report_md"],
                        "copy_to_gpt_research_prompt": result["statistical_report"]["copy_to_gpt_research_prompt"],
                        "evidence_boundary": result["statistical_report"]["evidence_boundary"],
                    },
                    "counts": result["snapshot"]["counts"],
                    "candidate_only": True,
                    "formal_trusted_consumption": False,
                    "no_openai_api_called": True,
                }
            )
            return
        if parsed.path == "/api/dashboard/generate_morningstar_report":
            from scripts.run_morningstar_research_workflow_integration_v1 import run_integration
            summary = run_integration()
            ms_root = PROJECT_ROOT / "runtime" / "morningstar_research_workflow_v1"
            self.send_json(
                {
                    "status": "ok",
                    "action": "generate_morningstar_report",
                    "data_product_id": summary["data_product_id"],
                    "version_id": summary["version_id"],
                    "api_calls_made": 0,
                    "no_openai_api_called": True,
                    "formal_trusted_consumption": False,
                    "parse_lab_affected": False,
                    "us_equity_standalone_excluded": True,
                    "tna_enf_blocked": True,
                    "outputs": {
                        "morningstar_workspace_index": str(ms_root / "workspace" / "morningstar_workspace_index.json"),
                        "morningstar_statistical_report": str(ms_root / "statistical_report" / "morningstar_statistical_report_v1.json"),
                        "morningstar_analysis_packet": str(ms_root / "analysis_packet" / "morningstar_analysis_packet_integration_v1.json"),
                        "morningstar_evidence_boundary": str(ms_root / "analysis_packet" / "morningstar_analysis_packet_integration_v1.json"),
                    },
                }
            )
            return
        if parsed.path == "/api/dashboard/classify_uploaded_report":
            raw_report = str(payload.get("raw_report") or "")
            output_name = str(payload.get("output_name") or "api_report_upload_action")
            result = classify_and_save_uploaded_report(raw_report, output_name)
            self.send_json(
                {
                    "status": "ok",
                    "action": "classify_uploaded_report",
                    "classification": result,
                    "candidate_only": True,
                    "formal_trusted_consumption": False,
                    "no_openai_api_called": True,
                }
            )
            return
        if parsed.path == "/api/dashboard/morningstar/token":
            self._handle_token_save(payload)
            return
        if parsed.path == "/api/dashboard/data_sources/morningstar/update":
            self._handle_morningstar_update()
            return
        self.send_json({"status": "not_found", "path": parsed.path}, status=404)

    def serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            path = FRONTEND_ROOT / "index.html"
        else:
            rel = request_path.lstrip("/")
            path = (FRONTEND_ROOT / rel).resolve()
            if FRONTEND_ROOT.resolve() not in path.parents and path != FRONTEND_ROOT.resolve():
                self.send_error(403)
                return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content = path.read_bytes()
        mime, _ = mimetypes.guess_type(path.name)
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def serve_download(self, query: str) -> None:
        raw_path = parse_qs(query).get("path", [""])[0]
        path = Path(unquote(raw_path)).resolve()
        allowed_roots = [
            PROJECT_ROOT.resolve(),
            RUNTIME_ROOT.resolve(),
            Path("Z:/data_lake_master").resolve(),
        ]
        if not any(path == root or root in path.parents for root in allowed_roots):
            self.send_error(403)
            return
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        content = path.read_bytes()
        mime, _ = mimetypes.guess_type(path.name)
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Morningstar Token Management ──
    SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"

    def _load_secrets(self) -> dict:
        if not self.SECRETS_PATH.exists():
            return {}
        return json.loads(self.SECRETS_PATH.read_text(encoding="utf-8"))

    def _save_secrets(self, data: dict) -> None:
        self.SECRETS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _mask_token(self, token: str) -> str:
        if not token or len(token) < 4:
            return "****"
        return "****" + token[-4:]

    def _decode_jwt_exp(self, token: str):
        import base64 as b64
        try:
            parts = token.split(".")
            if len(parts) < 2: return None
            p = parts[1]; pad = 4 - len(p) % 4
            if pad != 4: p += "=" * pad
            return json.loads(b64.urlsafe_b64decode(p)).get("exp")
        except: return None

    def _handle_token_save(self, payload: dict) -> None:
        token = str(payload.get("md_auth_token") or "").strip()
        hint = str(payload.get("account_hint") or "")
        if not token:
            self.send_json({"status": "error", "reason": "empty_token"}, status=400)
            return
        secrets = self._load_secrets()
        ms = secrets.setdefault("morningstar", {})
        old_hint = ms.get("account_hint", "")
        ms["md_auth_token"] = token
        ms["token_saved_at"] = datetime.now(timezone.utc).isoformat()
        ms["token_expires_hours"] = 24
        ms["token_source"] = "dashboard_manual_input"
        if hint: ms["account_hint"] = hint
        elif old_hint: ms["account_hint"] = old_hint
        self._save_secrets(secrets)
        masked = self._mask_token(token)
        sys.stderr.write(f"dashboard_v1_action_server: morningstar token saved masked={masked}\n")
        self.send_json({
            "status": "ok", "masked_token": masked,
            "saved_at": ms["token_saved_at"],
            "expires_hours": 24,
            "account_hint": ms.get("account_hint", ""),
        })

    def _handle_token_status(self) -> None:
        from datetime import timezone as tz, timedelta
        secrets = self._load_secrets()
        ms = secrets.get("morningstar", {})
        token = ms.get("md_auth_token", "")
        saved_at = ms.get("token_saved_at", "")
        expires_h = int(ms.get("token_expires_hours", 24))
        fallback_used = False

        if not saved_at:
            # fallback: file mtime
            try:
                mtime = self.SECRETS_PATH.stat().st_mtime
                saved_at = datetime.fromtimestamp(mtime, tz.utc).isoformat()
                fallback_used = True
            except: saved_at = ""

        remaining_s = 0; remaining_h = 0; remaining_m = 0
        estimated_expires = ""; expired_est = False; expiring_soon = False

        if saved_at:
            try:
                saved_dt = datetime.fromisoformat(saved_at)
                estimated_expires_dt = saved_dt + timedelta(hours=expires_h)
                estimated_expires = estimated_expires_dt.isoformat()
                now_dt = datetime.now(tz.utc)
                remaining_s = max(0, (estimated_expires_dt - now_dt).total_seconds())
                remaining_h = remaining_s / 3600
                remaining_m = remaining_s / 60
                expired_est = now_dt > estimated_expires_dt
                expiring_soon = not expired_est and remaining_h < 2
            except: pass

        status_text = "missing"
        if token:
            if expired_est: status_text = "expired_estimated"
            elif expiring_soon: status_text = "expiring_soon"
            else: status_text = "valid_estimated"

        jwt_exp = self._decode_jwt_exp(token) if token else None

        self.send_json({
            "token_available": bool(token),
            "masked_token": self._mask_token(token) if token else None,
            "token_saved_at": saved_at,
            "estimated_expires_at": estimated_expires,
            "remaining_seconds": round(remaining_s),
            "remaining_hours": round(remaining_h, 1),
            "remaining_minutes": round(remaining_m, 1),
            "expired_estimated": expired_est,
            "expiring_soon": expiring_soon,
            "status": status_text,
            "jwt_exp": jwt_exp,
            "account_hint": ms.get("account_hint", ""),
            "fallback_used": fallback_used,
            "token_source": ms.get("token_source", "unknown"),
        })

    def _handle_morningstar_update(self) -> None:
        from scripts.run_morningstar_manual_database_update_v1 import run_morningstar_update
        result = run_morningstar_update()
        self.send_json(result)

    def _handle_morningstar_source_status(self) -> None:
        p = PROJECT_ROOT / "runtime" / "morningstar_manual_update" / "morningstar_latest_status.json"
        if p.exists():
            self.send_json(json.loads(p.read_text(encoding="utf-8")))
        else:
            self.send_json({"source_id":"morningstar","status":"no_data","last_run_status":"never_run"})

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("dashboard_v1_action_server: " + (format % args) + "\n")


def run_server(host: str, port: int) -> None:
    if not (RUNTIME_ROOT / "dashboard_v1_summary.json").exists() or not (FRONTEND_ROOT / "index.html").exists():
        run_dashboard_v1()
    write_json(
        RUNTIME_ROOT / "action_server_last_start.json",
        {
            "host": host,
            "port": port,
            "url": f"http://{host}:{port}/",
            "legacy_streamlit_used": False,
            "no_openai_api_called": True,
        },
    )
    server = ThreadingHTTPServer((host, port), DashboardActionHandler)
    print(f"FR Dashboard v1 action server listening at http://{host}:{port}/")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run FR Dashboard v1 local action server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5188)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
