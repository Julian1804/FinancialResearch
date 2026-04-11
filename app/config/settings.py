import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
APP_DIR = BASE_DIR / "app"
CONFIG_DIR = APP_DIR / "config"

def _resolve_data_dir() -> Path:
    explicit = os.getenv("FIN_RESEARCH_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)

    qnap_enabled = os.getenv("QNAP_ENABLED", "false").strip().lower() == "true"
    qnap_mount = os.getenv("QNAP_DATA_MOUNT", "").strip()
    qnap_subdir = os.getenv("QNAP_PROJECT_SUBDIR", "financial_research_data").strip() or "financial_research_data"
    if qnap_enabled and qnap_mount:
        return Path(qnap_mount) / qnap_subdir

    return BASE_DIR / "data"

DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_DIR = DATA_DIR / "_system"
SYSTEM_DIR.mkdir(parents=True, exist_ok=True)

AGENT_REGISTRY_PATH = CONFIG_DIR / "agent_registry.json"
LLM_PROFILES_PATH = CONFIG_DIR / "llm_profiles.json"
INDUSTRY_METRIC_PROFILE_PATH = CONFIG_DIR / "industry_metric_profiles.json"
SQLITE_DB_PATH = SYSTEM_DIR / "research_index.db"

SCHEMA_VERSION = "v1"
DEFAULT_FULLTEXT_PREVIEW_CHARS = 1800

SUBFOLDERS = {
    "raw": "年报",
    "parsed": "年报解析",
    "extracted": "年报提取",
    "analysis": "年报分析",
    "page_images": "年报页面图片",
    "qa_index": "问答索引",
}

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.2").strip()

ALIYUN_API_KEY = os.getenv("ALIYUN_API_KEY", "").strip()
ALIYUN_BASE_URL = os.getenv("ALIYUN_BASE_URL", "").strip()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip()

DEFAULT_LLM_PROFILE = os.getenv("DEFAULT_LLM_PROFILE", "aliyun_text_free").strip()
DEFAULT_VISION_PROFILE = os.getenv("DEFAULT_VISION_PROFILE", "aliyun_vision_free").strip()

PARSE_ENABLE_MULTIMODAL = os.getenv("PARSE_ENABLE_MULTIMODAL", "true").strip().lower() == "true"
PARSE_MAX_MULTIMODAL_PAGES = max(0, int(os.getenv("PARSE_MAX_MULTIMODAL_PAGES", "8") or 8))
PARSE_RENDER_SCALE = max(1.0, float(os.getenv("PARSE_RENDER_SCALE", "1.6") or 1.6))
PARSE_TEXT_RESCUE_PAGE_LIMIT = max(1, int(os.getenv("PARSE_TEXT_RESCUE_PAGE_LIMIT", "30") or 30))


def _load_json_config(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_agent_registry() -> dict:
    return _load_json_config(AGENT_REGISTRY_PATH, {})


def load_llm_profiles() -> dict:
    payload = _load_json_config(LLM_PROFILES_PATH, {})
    if isinstance(payload, dict) and "profiles" in payload:
        return payload
    return {"profiles": payload if isinstance(payload, dict) else {}}


def load_industry_metric_profiles() -> dict:
    return _load_json_config(INDUSTRY_METRIC_PROFILE_PATH, {})
