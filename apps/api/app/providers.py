"""Server-only generation settings. Gemini is preferred when both keys are set."""

import os
from dataclasses import dataclass, field

from fastapi import HTTPException


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    endpoint: str
    key: str = field(repr=False)


def generation_provider():
    selected = os.getenv("LLM_PROVIDER", "auto").strip().lower()
    if selected == "evidence":
        return None
    if selected not in ("auto", "gemini", "openai"):
        raise HTTPException(
            503, "LLM_PROVIDER must be auto, gemini, openai, or evidence."
        )
    if selected in ("auto", "gemini") and (
        key := os.getenv("GEMINI_API_KEY", "").strip()
    ):
        return Provider(
            "gemini",
            os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip(),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            key,
        )
    if selected in ("auto", "openai") and (
        key := os.getenv("OPENAI_API_KEY", "").strip()
    ):
        return Provider(
            "openai",
            os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip(),
            "https://api.openai.com/v1/chat/completions",
            key,
        )
    # An explicit provider never falls through to another provider or paid key.
    return None


def provider_error(provider, status):
    label = "Gemini" if provider.name == "gemini" else "OpenAI"
    if status in (401, 403):
        return HTTPException(
            502,
            f"{label} rejected the API key or project access. Check the server key and API permissions.",
        )
    if status == 429:
        return HTTPException(
            503,
            f"{label}'s request limit or quota was reached. Wait for the quota to reset and check your project's limits. No other provider was used.",
        )
    if status == 404:
        return HTTPException(
            502,
            f"The configured {label} model is unavailable for this project. Check the server model setting.",
        )
    if status >= 500:
        return HTTPException(
            503,
            f"{label} is temporarily unavailable. Please try AI synthesis again later.",
        )
    return HTTPException(
        502,
        f"{label} could not complete the answer. Please retry; check server configuration if this persists.",
    )
