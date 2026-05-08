from __future__ import annotations

from fastapi import FastAPI

from backend.app.core.config import APP_NAME, API_PREFIX
from backend.app.core.logging import configure_logging
from backend.app.modules.financial_report.routers.parse_router import router as financial_report_parse_router


configure_logging()

app = FastAPI(title=APP_NAME)


@app.get(f"{API_PREFIX}/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "financial_research_backend"}


# Module routers. Business flows are intentionally not wired yet.
app.include_router(financial_report_parse_router)
