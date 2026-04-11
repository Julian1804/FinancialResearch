from typing import Optional

from config.settings import DEFAULT_LLM_PROFILE, load_agent_registry
from services.llm_gateway_service import call_profile_chat


def _legacy_profile_from_provider(provider: str) -> str:
    provider = (provider or "").strip().lower()
    if provider in {"aliyun_qwen_compatible", "aliyun", "openai_compatible"}:
        return "aliyun_text_free"
    if provider in {"deepseek_compatible", "deepseek"}:
        return "deepseek_text"
    return DEFAULT_LLM_PROFILE


def _get_agent_config(agent_name: str, fallback_agent: Optional[str] = None) -> dict:
    registry = load_agent_registry()
    config = registry.get(agent_name)
    if config and config.get("enabled", False):
        return config
    if fallback_agent:
        fallback = registry.get(fallback_agent)
        if fallback and fallback.get("enabled", False):
            return fallback
    return {"enabled": True, "mode": "cloud", "profile_name": DEFAULT_LLM_PROFILE, "timeout": 300}


def call_agent_chat(agent_name: str, system_prompt: str, user_prompt: str, fallback_agent: Optional[str] = None) -> str:
    config = _get_agent_config(agent_name, fallback_agent=fallback_agent)
    profile_name = config.get("profile_name") or _legacy_profile_from_provider(config.get("provider", ""))
    requested_model = (config.get("model") or "").strip()
    return call_profile_chat(
        profile_name=profile_name,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        requested_model=requested_model,
    )
