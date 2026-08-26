from __future__ import annotations

import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_provider: str = "auto"

    # Google Gemini (free tier)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"

    # Groq (free tier — fastest inference)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # Ollama (local — no API key)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"

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


def build_llm_with_fallback(temperature: float | None = None):
    s = get_settings()
    provider = s.llm_provider.lower().strip()

    # Direct provider mode — no fallback chain
    if provider in ("gemini", "groq", "ollama"):
        return build_llm(temperature)

    # Auto mode — fallback chain across Gemini models + Groq
    from langchain_google_genai import ChatGoogleGenerativeAI

    def _gemini(model: str):
        kwargs: dict = {"model": model, "google_api_key": s.gemini_api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        return ChatGoogleGenerativeAI(**kwargs)

    primary = _gemini(s.gemini_model)

    fallbacks = []
    _ALT_GEMINI = ["gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.7-flash"]
    for alt in _ALT_GEMINI:
        if alt != s.gemini_model:
            fallbacks.append(_gemini(alt))

    if s.groq_api_key:
        from langchain_groq import ChatGroq
        groq_kwargs: dict = {"model": s.groq_model, "groq_api_key": s.groq_api_key}
        if temperature is not None:
            groq_kwargs["temperature"] = temperature
        fallbacks.append(ChatGroq(**groq_kwargs))

    if fallbacks:
        return primary.with_fallbacks(fallbacks)
    return primary


def get_provider_label() -> str:
    s = get_settings()
    provider = s.llm_provider.lower().strip()
    if provider == "auto":
        return f"Auto ({s.gemini_model} + fallbacks)"
    if provider == "gemini":
        return f"{s.gemini_model} (direct)"
    if provider == "groq":
        return f"{s.groq_model} (direct)"
    if provider == "ollama":
        return f"{s.ollama_model} (local)"
    return f"Auto ({s.gemini_model} + fallbacks)"
