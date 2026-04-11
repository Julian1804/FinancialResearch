import base64
import mimetypes
import os
from pathlib import Path
from typing import List, Optional

from openai import OpenAI
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)

from config.settings import DEFAULT_LLM_PROFILE, DEFAULT_VISION_PROFILE, load_llm_profiles


class LLMProviderError(Exception):
    pass


def _load_profiles() -> dict:
    return load_llm_profiles().get("profiles", {})


def get_profile(profile_name: str) -> dict:
    profiles = _load_profiles()
    profile = profiles.get(profile_name)
    if not profile:
        raise LLMProviderError(f"未找到 LLM Profile：{profile_name}")
    if not profile.get("enabled", False):
        raise LLMProviderError(f"LLM Profile 已禁用：{profile_name}")
    return profile


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _build_client(profile: dict) -> OpenAI:
    api_key_env = profile.get("api_key_env", "")
    base_url_env = profile.get("base_url_env", "")
    api_key = os.getenv(api_key_env, "").strip()
    base_url = _normalize_base_url(os.getenv(base_url_env, ""))

    if not api_key:
        raise LLMProviderError(f"缺少 API Key：请配置环境变量 {api_key_env}")
    if not base_url:
        raise LLMProviderError(f"缺少 Base URL：请配置环境变量 {base_url_env}")

    return OpenAI(api_key=api_key, base_url=base_url)


def _candidate_models(profile: dict, requested_model: str = "") -> List[str]:
    models = []
    if requested_model:
        models.append(requested_model)
    models.extend(profile.get("models", []))
    if profile.get("model"):
        models.append(profile.get("model"))
    dedup = []
    seen = set()
    for item in models:
        item = (item or "").strip()
        if item and item not in seen:
            seen.add(item)
            dedup.append(item)
    return dedup


def _is_retryable_model_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    keywords = [
        "quota", "free quota", "rate limit", "429", "404", "not found",
        "model not found", "does not exist", "service unavailable",
        "temporarily unavailable", "engine not found", "unsupported model",
        "invalid model", "not support", "forbidden model"
    ]
    return any(k in msg for k in keywords)


def _format_attempt_error(profile_name: str, model: str, exc: Exception) -> str:
    return f"profile={profile_name} model={model} error={exc.__class__.__name__}: {exc}"


def _extract_message_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif "text" in item:
                    text_value = item.get("text")
                    if isinstance(text_value, dict):
                        parts.append(text_value.get("value", ""))
                    else:
                        parts.append(str(text_value or ""))
            else:
                parts.append(str(item))
        return "\n".join([p for p in parts if p])
    if isinstance(content, dict):
        if "text" in content:
            text_value = content.get("text")
            if isinstance(text_value, dict):
                return text_value.get("value", "") or ""
            return str(text_value or "")
        return str(content)
    return str(content)


def _run_text_completion(profile_name: str, model: str, system_prompt: str, user_prompt: str) -> str:
    profile = get_profile(profile_name)
    client = _build_client(profile)
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=profile.get("temperature", 0.2),
        timeout=profile.get("timeout", 300),
    )
    if profile.get("response_format") == "json_object":
        kwargs["response_format"] = {"type": "json_object"}
    try:
        response = client.chat.completions.create(**kwargs)
    except BadRequestError:
        kwargs.pop("response_format", None)
        response = client.chat.completions.create(**kwargs)
    message = response.choices[0].message
    return _extract_message_text(getattr(message, "content", None))


def _image_to_data_uri(image_path: str | Path) -> str:
    image_path = Path(image_path)
    mime_type, _ = mimetypes.guess_type(str(image_path))
    mime_type = mime_type or "image/png"
    raw = image_path.read_bytes()
    encoded = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def _run_vision_completion(profile_name: str, model: str, prompt: str, image_path: str | Path) -> str:
    profile = get_profile(profile_name)
    client = _build_client(profile)
    image_url = _image_to_data_uri(image_path)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=profile.get("temperature", 0.0),
        timeout=profile.get("timeout", 180),
    )
    message = response.choices[0].message
    return _extract_message_text(getattr(message, "content", None))


def _call_with_failover(
    *,
    profile_name: str,
    requested_model: str = "",
    runner,
    fallback_profiles: Optional[List[str]] = None,
    **runner_kwargs,
) -> str:
    attempts = []
    visited_profiles = set()

    def _try_profile(name: str):
        if not name or name in visited_profiles:
            return None
        visited_profiles.add(name)
        profile = get_profile(name)
        models = _candidate_models(profile, requested_model=requested_model)
        local_fallbacks = list(fallback_profiles or []) + profile.get("fallback_profiles", [])

        for model in models:
            try:
                return runner(name, model, **runner_kwargs)
            except (NotFoundError, RateLimitError, APITimeoutError, APIConnectionError, InternalServerError, BadRequestError, APIError, LLMProviderError) as exc:
                attempts.append(_format_attempt_error(name, model, exc))
                if not _is_retryable_model_error(exc) and not isinstance(exc, (APITimeoutError, APIConnectionError, InternalServerError, APIError)):
                    break

        for fallback_name in local_fallbacks:
            result = _try_profile(fallback_name)
            if result:
                return result
        return None

    result = _try_profile(profile_name)
    if result:
        return result

    attempts_text = "\n".join(attempts) if attempts else "无具体尝试记录"
    raise LLMProviderError("所有候选模型均调用失败。\n" + attempts_text)


def call_profile_chat(profile_name: str, system_prompt: str, user_prompt: str, requested_model: str = "") -> str:
    return _call_with_failover(
        profile_name=profile_name or DEFAULT_LLM_PROFILE,
        requested_model=requested_model,
        runner=_run_text_completion,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def call_profile_vision(profile_name: str, prompt: str, image_path: str | Path, requested_model: str = "") -> str:
    return _call_with_failover(
        profile_name=profile_name or DEFAULT_VISION_PROFILE,
        requested_model=requested_model,
        runner=_run_vision_completion,
        prompt=prompt,
        image_path=image_path,
    )
