"""Render's single-service demo entry point; never loads the local .env."""

import os

import uvicorn

if __name__ == "__main__":
    os.environ["APP_ENV"] = "demo"
    os.environ["COOKIE_SECURE"] = "true"
    os.environ["EMBEDDED_WORKER"] = "false"
    os.environ["EMBEDDING_MODEL"] = ""
    os.environ["AUTO_MIGRATE"] = "true"
    # Curated fixtures use their own reviewer login and database-backed originals.
    os.environ["AUTH_PROVIDER"] = "local"
    os.environ["ORIGINAL_STORAGE"] = "database"
    os.environ["PUBLIC_URL"] = os.getenv("RENDER_EXTERNAL_URL", os.getenv("PUBLIC_URL", "")).rstrip("/")
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), workers=1, access_log=False)
