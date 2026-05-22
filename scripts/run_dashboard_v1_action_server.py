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
