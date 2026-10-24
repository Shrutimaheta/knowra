"""Remote restricted parser in production; local compatibility for development."""

import base64
import os

import httpx
from app.extraction import ExtractionError
from fastapi import HTTPException


def remote(operation, data, **options):
    endpoint = os.getenv("PARSER_URL", "").rstrip("/")
    if not endpoint:
        if os.getenv("APP_ENV") == "production":
            raise HTTPException(503, "Document processing is not configured.")
        return None
    try:
        response = httpx.post(
            endpoint + "/process",
            json={"operation": operation, "data": base64.b64encode(data).decode(), **options},
            timeout=httpx.Timeout(310, connect=5),
            trust_env=False,
        )
        if response.status_code == 422:
            raise ExtractionError("This document could not be processed. Use a valid, readable file.")
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Document processing is unavailable. Please retry shortly.") from None


def validate(filename, data):
    try:
        result = remote("validate", data, filename=filename)
    except ExtractionError:
        raise HTTPException(400, "Use a valid, readable document or image.") from None
    if result is not None:
        return result["pages"]
    from app.rag import parse_file

    return parse_file(filename, data)


def extract(filename, data, pages):
    result = remote("extract", data, filename=filename, pages=pages)
    if result is not None:
        return result["pages"], result["layout"]
    from app.extraction import extract_image, extract_pdf

    return extract_pdf(data, pages) if filename.lower().endswith(".pdf") else extract_image(data)


def page_image(data, number):
    from app.malware import scan

    scan(data)
    result = remote("image", data, number=number)
    if result is not None:
        return base64.b64decode(result["image"], validate=True)
    from app.extraction import page_image as local_image

    return local_image(data, number)


def highlight(pages, number, quote, data=None):
    if data is not None:
        from app.malware import scan

        scan(data)
        result = remote("highlight", data, pages=pages, number=number, quote=quote)
        if result is not None:
            return result
    from app.evidence import highlight as local_highlight

    return local_highlight(pages, number, quote, data)
