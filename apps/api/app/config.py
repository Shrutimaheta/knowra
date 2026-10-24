"""Fail closed on incomplete production configuration without exposing secrets."""

import os
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url


def validate_runtime():
    if os.getenv("APP_ENV") == "demo":
        validate_demo()
        return
    if os.getenv("APP_ENV", "development") != "production":
        return
    problems = []
    public = urlsplit(os.getenv("PUBLIC_URL", ""))
    if (
        public.scheme != "https"
        or not public.hostname
        or public.username
        or public.password
        or public.path not in ("", "/")
        or public.query
        or public.fragment
    ):
        problems.append("PUBLIC_URL must be an HTTPS origin")
    if os.getenv("COOKIE_SECURE") != "true":
        problems.append("COOKIE_SECURE must be true")
    try:
        database = make_url(os.getenv("DATABASE_URL", ""))
        if database.get_backend_name() != "postgresql":
            raise ValueError
        if not database.password or "replace_with" in database.password:
            raise ValueError
    except Exception:
        problems.append("DATABASE_URL must configure PostgreSQL with a real password")
    if os.getenv("AUTO_MIGRATE", "true") != "false":
        problems.append("AUTO_MIGRATE must be false; run the release migrator first")
    if os.getenv("EMBEDDED_WORKER", "true") != "false":
        problems.append("EMBEDDED_WORKER must be false; run the dedicated worker")
    if not os.getenv("SMTP_HOST") or "@" not in os.getenv("SMTP_FROM", ""):
        problems.append("SMTP_HOST and a valid SMTP_FROM are required")
    if bool(os.getenv("SMTP_USER")) != bool(os.getenv("SMTP_PASSWORD")):
        problems.append("SMTP_USER and SMTP_PASSWORD must be supplied together")
    if not os.getenv("CLAMAV_HOST"):
        problems.append("CLAMAV_HOST is required for upload scanning")
    if os.getenv("PARSER_URL") != "http://parser:8001":
        problems.append("PARSER_URL must point to the internal restricted parser")
    if problems:
        raise RuntimeError("Production configuration: " + "; ".join(problems))


def validate_demo():
    problems = []
    public = urlsplit(os.getenv("PUBLIC_URL", ""))
    if public.scheme != "https" or not public.hostname or public.username or public.path not in ("", "/") or public.query or public.fragment:
        problems.append("PUBLIC_URL must be an HTTPS origin")
    if os.getenv("COOKIE_SECURE") != "true":
        problems.append("COOKIE_SECURE must be true")
    try:
        url = make_url(os.getenv("DATABASE_URL", ""))
        if url.get_backend_name() != "postgresql" or not url.password or url.query.get("sslmode") not in ("require", "verify-ca", "verify-full"):
            raise ValueError
    except Exception:
        problems.append("DATABASE_URL must be a dedicated PostgreSQL connection with TLS")
    if not 12 <= len(os.getenv("DEMO_PASSWORD", "")) <= 128:
        problems.append("Set a private DEMO_PASSWORD of 12–128 characters")
    if os.getenv("EMBEDDING_MODEL", "").strip() or os.getenv("EMBEDDED_WORKER", "true") != "false":
        problems.append("The lightweight demo requires embeddings and embedded worker disabled")
    if problems:
        raise RuntimeError("Demo configuration: " + "; ".join(problems))
