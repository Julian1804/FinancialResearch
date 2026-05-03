from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

APP_NAME = os.getenv("FINANCIAL_RESEARCH_APP_NAME", "FinancialResearch")
APP_ENV = os.getenv("FINANCIAL_RESEARCH_APP_ENV", "local")
API_PREFIX = os.getenv("FINANCIAL_RESEARCH_API_PREFIX", "/api")

PARSE_LAB_BASE_URL = os.getenv("PARSE_LAB_BASE_URL", "http://127.0.0.1:8021")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = Path(os.getenv("FINANCIAL_RESEARCH_RUNTIME_ROOT", PROJECT_ROOT / "runtime"))
DATA_ROOT = Path(os.getenv("FINANCIAL_RESEARCH_DATA_ROOT", PROJECT_ROOT / "data"))
NAS_ROOT = os.getenv("FINANCIAL_RESEARCH_NAS_ROOT", "").strip() or None
