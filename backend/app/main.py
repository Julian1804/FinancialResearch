from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.composition import capability_catalog, register_backend_capabilities
from backend.app.core.config import API_PREFIX, APP_NAME
from backend.app.core.diagnostics import install_diagnostic_boundary
from backend.app.core.logging import configure_logging
from backend.app.core.readiness import active_v1_readiness


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(title=APP_NAME)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
        expose_headers=["X-FR-Request-ID", "X-FR-Operation-ID", "X-FR-Error-Class"],
    )
    install_diagnostic_boundary(application)

    @application.get(f"{API_PREFIX}/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "financial_research_backend"}

    @application.get(f"{API_PREFIX}/readiness")
    def readiness():
        result = active_v1_readiness()
        return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503)

    @application.get(f"{API_PREFIX}/capabilities")
    def capabilities() -> dict[str, object]:
        return capability_catalog()

    register_backend_capabilities(application)
    return application


app = create_app()
