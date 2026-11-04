from __future__ import annotations

import argparse
import mimetypes
import posixpath
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "frontend_web" / "src" / "dashboard_v1"
BACKEND_ORIGIN = "http://127.0.0.1:8000"
CURRENT_PRODUCT_FILES = {
    "index.html",
    "morningstar_token_panel.html",
    "workspace_v1/styles/workspace.css",
    "workspace_v1/js/main.js",
    "workspace_v1/js/api.js",
    "workspace_v1/js/chart-model.js",
    "workspace_v1/js/components.js",
    "workspace_v1/js/fund-export.js",
    "workspace_v1/js/equity-export.js",
    "workspace_v1/js/fund-presentation.js",
    "workspace_v1/js/navigation.js",
    "workspace_v1/js/state.js",
    "workspace_v1/js/lifecycle.js",
    "workspace_v1/js/user-data-catalog.js",
    "workspace_v1/js/view-registry.js",
    "workspace_v1/js/views/database-status.js",
    "workspace_v1/js/views/overview.js",
    "workspace_v1/js/views/public-fund.js",
    "workspace_v1/js/views/china-equity.js",
    "workspace_v1/js/views/comparative-series.js",
    "workspace_v1/js/views/modeling-stage1.js",
    "workspace_v1/js/views/modeling-stage1-contract.mjs",
    "workspace_v1/js/views/local-tools.js",
    "workspace_v1/js/views/data-update.js",
    "workspace_v1/js/views/data-status.js",
}


def loopback_backend_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("loopback_backend_origin_required") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
            or port is None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or parsed.username or parsed.password):
        raise ValueError("loopback_backend_origin_required")
    return f"http://{parsed.hostname}:{port}"


class LocalGatewayHandler(BaseHTTPRequestHandler):
    server_version = "FRLocalGateway/1.0"

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy()
            return
        self.serve_static()

    def do_POST(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy()
            return
        self.send_error(405, "Method Not Allowed")

    def do_OPTIONS(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy()
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - - [%s] %s" % (self.client_address[0], self.log_date_time_string(), fmt % args), flush=True)

    def serve_static(self) -> None:
        target = self.static_target()
        if target is None or not target.exists() or not target.is_file():
            self.send_error(404, "Not Found")
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-FR-Local-Gateway", "static")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def static_target(self) -> Path | None:
        parsed = urlsplit(self.path)
        raw_path = parsed.path or "/"
        normalized = posixpath.normpath(unquote(raw_path)).lstrip("/")
        if normalized in {"", "."}:
            normalized = "index.html"
        if normalized not in CURRENT_PRODUCT_FILES:
            return None
        candidate = (STATIC_ROOT / normalized).resolve()
        try:
            candidate.relative_to(STATIC_ROOT.resolve())
        except ValueError:
            return None
        return candidate

    def proxy(self) -> None:
        backend_origin = getattr(self.server, "backend_origin", BACKEND_ORIGIN)
        target_url = backend_origin + self.path
        body = None
        if self.command in {"POST", "PUT", "PATCH"}:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length) if length else b""
        headers = {
            "Host": urlsplit(backend_origin).netloc,
            "User-Agent": "fr-local-frontend-gateway",
        }
        for key in ("Content-Type", "Accept", "Origin"):
            value = self.headers.get(key)
            if value:
                headers[key] = value
        request = Request(target_url, data=body, headers=headers, method=self.command)
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
                self.send_response(response.status)
                self.copy_response_headers(response.headers.items(), len(data))
                self.end_headers()
                self.wfile.write(data)
        except HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.copy_response_headers(exc.headers.items(), len(data))
            self.end_headers()
            self.wfile.write(data)
        except URLError:
            data = b'{"detail":"backend_unavailable"}'
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-FR-Local-Gateway", "api-proxy")
            self.end_headers()
            self.wfile.write(data)

    def copy_response_headers(self, items, length: int) -> None:
        skipped = {"connection", "content-length", "transfer-encoding", "server", "date"}
        for key, value in items:
            if key.lower() not in skipped:
                self.send_header(key, value)
        self.send_header("Content-Length", str(length))
        self.send_header("X-FR-Local-Gateway", "api-proxy")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--backend-origin", default=BACKEND_ORIGIN)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("loopback_host_required")
    try:
        backend_origin = loopback_backend_origin(args.backend_origin)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    server = ThreadingHTTPServer((args.host, args.port), LocalGatewayHandler)
    server.backend_origin = backend_origin
    print(f"FR local frontend gateway serving {STATIC_ROOT} and proxying /api to {server.backend_origin}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
