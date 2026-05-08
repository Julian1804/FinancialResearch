from __future__ import annotations

from pathlib import Path

from backend.app.core.config import DATA_ROOT, NAS_ROOT, PROJECT_ROOT, RUNTIME_ROOT


BACKEND_ROOT = PROJECT_ROOT / "backend"
BACKEND_APP_ROOT = BACKEND_ROOT / "app"
DOCS_ROOT = PROJECT_ROOT / "docs"
FRONTEND_ROOT = PROJECT_ROOT / "frontend_web"

RUNTIME_TASKS_ROOT = RUNTIME_ROOT / "tasks"
RUNTIME_RESULTS_ROOT = RUNTIME_ROOT / "results"
DATA_DOCUMENTS_ROOT = DATA_ROOT / "documents"
DATA_REGISTRY_ROOT = DATA_ROOT / "registry"
NAS_ROOT_PATH = Path(NAS_ROOT) if NAS_ROOT else None
