"""Private branch-scoped S3 originals; authorization stays in the app routes."""

import os
from functools import lru_cache

from fastapi import HTTPException


def enabled():
    return os.getenv("ORIGINAL_STORAGE") == "neon"


@lru_cache(maxsize=4)
def _client(endpoint, region, access, secret):
    import boto3
    from botocore.config import Config

    return boto3.client("s3", endpoint_url=endpoint, region_name=region,
                        aws_access_key_id=access, aws_secret_access_key=secret,
                        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                                      connect_timeout=5, read_timeout=20, retries={"max_attempts": 2}))


def client():
    return _client(*(os.environ[key] for key in ("AWS_ENDPOINT_URL_S3", "AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")))


def bucket():
    return os.getenv("NEON_STORAGE_BUCKET", "assets")


def put(version, data):
    key = "originals/" + version
    try:
        client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType="application/octet-stream")
        return key
    except Exception:
        raise HTTPException(503, "Original-file storage is unavailable. Please retry.") from None


def get(key):
    try:
        body = client().get_object(Bucket=bucket(), Key=key)["Body"]
        try:
            data = body.read(10 * 1024 * 1024 + 1)
        finally:
            body.close()
        if len(data) > 10 * 1024 * 1024:
            raise ValueError("Oversized stored original")
        return data
    except Exception:
        raise HTTPException(503, "Original-file storage is unavailable. Please retry.") from None


def original(version):
    if version.get("original_key"):
        return get(version["original_key"])
    return bytes(version["original"]) if version["original"] is not None else None
