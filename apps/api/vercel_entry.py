"""Vercel ASGI entry point. Database release tasks run separately."""

from app.vercel_runtime import configure

configure()

from app.main import app  # noqa: E402, F401
