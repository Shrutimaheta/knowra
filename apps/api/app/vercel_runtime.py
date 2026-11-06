"""Lightweight public workspace settings; credentials stay in Vercel's environment."""

import os


def configure():
    os.environ.update({
        "APP_ENV": "demo",
        "COOKIE_SECURE": "true",
        "AUTH_PROVIDER": "local",
        "ORIGINAL_STORAGE": "database",
        "DEMO_PUBLIC_DASHBOARD": "true",
        "EMBEDDED_WORKER": "false",
        "EMBEDDING_MODEL": "",
        "WARM_EMBEDDINGS": "false",
        "AUTO_MIGRATE": "false",
        "DEMO_BOOTSTRAP": "false",
    })
    # Preview deployments have their own trusted origin, separate from production.
    if os.getenv("VERCEL_ENV") != "production" and os.getenv("VERCEL_URL"):
        os.environ["PUBLIC_URL"] = "https://" + os.environ["VERCEL_URL"]
    elif not os.getenv("PUBLIC_URL") and os.getenv("VERCEL_PROJECT_PRODUCTION_URL"):
        os.environ["PUBLIC_URL"] = "https://" + os.environ["VERCEL_PROJECT_PRODUCTION_URL"]
