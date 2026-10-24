"""Authenticated server-to-server calls; URLs/secrets never reach the browser."""

import os

import httpx
from fastapi import HTTPException


def source_integrity(document, version, user):
    url = os.getenv("NEON_FUNCTION_HELLO_BASE_URL")
    secret = os.getenv("KNOWRA_FUNCTION_SECRET")
    if not url or not secret:
        raise HTTPException(503, "Source verification is not configured.")
    try:
        result = httpx.post(url, headers={"X-Secret": secret},
                            json={"document": document, "version": version, "org": user["org"], "user": user["id"]},
                            follow_redirects=False, timeout=30)
        result.raise_for_status()
        return result.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Source verification is temporarily unavailable.") from None
