from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

APP_NAME = os.getenv("FINANCIAL_RESEARCH_APP_NAME", "FinancialResearch")
APP_ENV = os.getenv("FINANCIAL_RESEARCH_APP_ENV", "local")
# Every mounted router is part of the same public/local ``/api`` contract.
# Rejecting a conflicting override is safer than moving only health endpoints.
API_PREFIX = "/api"
CONFIGURED_API_PREFIX = os.getenv("FINANCIAL_RESEARCH_API_PREFIX", API_PREFIX)
if CONFIGURED_API_PREFIX != API_PREFIX:
    raise RuntimeError("FINANCIAL_RESEARCH_API_PREFIX cannot differ from the mounted /api router contract")

PARSE_LAB_BASE_URL = os.getenv("PARSE_LAB_BASE_URL", "http://127.0.0.1:8021")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = Path(os.getenv("FINANCIAL_RESEARCH_RUNTIME_ROOT", "").strip() or PROJECT_ROOT / "runtime")
DATA_ROOT = Path(os.getenv("FINANCIAL_RESEARCH_DATA_ROOT", "").strip() or PROJECT_ROOT / "data")
NAS_ROOT = os.getenv("FR_NAS_ROOT", "").strip() or None
