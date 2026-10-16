from __future__ import annotations

import os
import logging
from functools import lru_cache
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    llm_provider: str = "auto"

    # Google Gemini (free tier)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_fallback_models: str = (
        "gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.7-flash"
    )

    # Groq (free tier — fastest inference)
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_models: str = (
        "openai/gpt-oss-120b,qwen/qwen3.8-27b,openai/gpt-oss-20b"
    )

    # Ollama (local — no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"

    # MongoDB
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "studymate"

    # Network
    http_proxy: str = ""

    # App
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _apply_proxy() -> None:
    proxy = get_settings().http_proxy.strip()
    if proxy:
        for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ.setdefault(var, proxy)

        import ssl
        import warnings
        ssl._create_default_https_context = ssl._create_unverified_context
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        try:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:
            pass


_apply_proxy()


def build_llm(temperature: float | None = None):
    s = get_settings()
    provider = s.llm_provider.lower().strip()

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs: dict = {
            "model": s.gemini_model,
            "google_api_key": s.gemini_api_key,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "groq":
        from langchain_groq import ChatGroq
        kwargs = {
            "model": s.groq_model,
            "groq_api_key": s.groq_api_key,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return ChatGroq(**kwargs)

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        kwargs = {
            "model": s.ollama_model,
            "base_url": s.ollama_base_url,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return ChatOllama(**kwargs)

    # Fallback: default to gemini
    from langchain_google_genai import ChatGoogleGenerativeAI
    kwargs = {
        "model": s.gemini_model,
        "google_api_key": s.gemini_api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatGoogleGenerativeAI(**kwargs)


def build_groq_llm(model: str, temperature: float | None = None):
    s = get_settings()
    from langchain_groq import ChatGroq

    kwargs: dict = {"model": model, "groq_api_key": s.groq_api_key}
    if temperature is not None:
        kwargs["temperature"] = temperature
    return ChatGroq(**kwargs)


def _unique_models(primary: str, configured: str) -> list[str]:
    models = [primary] + [model.strip() for model in configured.split(",")]
    return list(dict.fromkeys(model for model in models if model))


def build_llm_candidates(temperature: float | None = None):
    s = get_settings()
    provider = s.llm_provider.lower().strip()

    from langchain_google_genai import ChatGoogleGenerativeAI

    def _gemini(model: str):
        kwargs: dict = {"model": model, "google_api_key": s.gemini_api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "groq":
        if not s.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return [
            build_groq_llm(model, temperature)
            for model in _unique_models(s.groq_model, s.groq_fallback_models)
        ]

    if provider == "ollama":
        return [build_llm(temperature)]

    gemini_models = [
        _gemini(model)
        for model in _unique_models(s.gemini_model, s.gemini_fallback_models)
    ]
    if provider == "gemini":
        return gemini_models

    if provider == "auto":
        groq_models = []
        if s.groq_api_key:
            groq_models = [
                build_groq_llm(model, temperature)
                for model in _unique_models(s.groq_model, s.groq_fallback_models)
            ]
        logger.info(
            "LLM auto mode configured: gemini_fallbacks=%s, groq_fallbacks=%s",
            ", ".join(_unique_models(s.gemini_model, s.gemini_fallback_models)),
            ", ".join(_unique_models(s.groq_model, s.groq_fallback_models))
            if s.groq_api_key else "none",
        )
        return gemini_models + groq_models

    return gemini_models


def build_llm_with_fallback(temperature: float | None = None):
    candidates = build_llm_candidates(temperature)
    primary, *fallbacks = candidates
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


def get_provider_label() -> str:
    provider = get_settings().llm_provider.lower().strip()
    if provider == "auto":
        return "Auto (Gemini + Groq fallbacks)"
    if provider == "gemini":
        return "Gemini (with fallbacks)"
    if provider == "groq":
        return "Groq (with fallbacks)"
    if provider == "ollama":
        return "Ollama (local)"
    return "Auto (Gemini + Groq fallbacks)"
