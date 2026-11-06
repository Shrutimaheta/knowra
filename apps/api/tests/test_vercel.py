import importlib.util
import os
from pathlib import Path

from app.vercel_runtime import configure


def test_vercel_does_not_run_release_tasks_on_cold_start(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("VERCEL_URL", "knowra-preview.vercel.app")
    monkeypatch.setenv("PUBLIC_URL", "https://knowra.example")
    for name in ("APP_ENV", "COOKIE_SECURE", "AUTH_PROVIDER", "ORIGINAL_STORAGE", "DEMO_PUBLIC_DASHBOARD", "EMBEDDED_WORKER", "EMBEDDING_MODEL", "WARM_EMBEDDINGS", "AUTO_MIGRATE", "DEMO_BOOTSTRAP"):
        monkeypatch.setenv(name, "old")
    configure()
    assert os.environ["PUBLIC_URL"] == "https://knowra-preview.vercel.app"
    assert all(os.environ[key] == "false" for key in ("AUTO_MIGRATE", "DEMO_BOOTSTRAP", "WARM_EMBEDDINGS", "EMBEDDED_WORKER"))
    assert os.environ["COOKIE_SECURE"] == "true"


def test_vercel_origin_checks_accept_exact_deployment_only(client, monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("VERCEL_URL", "knowra-preview.vercel.app")
    monkeypatch.setenv("PUBLIC_URL", "https://knowra.example")
    for origin in ("https://knowra-preview.vercel.app", "https://knowra.example"):
        # The origin passes, then the unauthenticated session is rejected normally.
        assert client.post("/api/v1/auth/logout", headers={"Origin": origin}).status_code == 401
    assert client.post("/api/v1/auth/logout", headers={"Origin": "https://attacker.example"}).status_code == 403


def test_vercel_package_contains_cdn_dashboard_without_private_files(tmp_path):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("vercel_package", root / "scripts/package_vercel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.package(tmp_path)
    names = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert not any(p.startswith(("data/", "tests/")) or ".env" in Path(p).name or p.endswith((".db", ".pyc")) for p in names)
    assert 'id="auth" class="auth-layout hidden"' in (tmp_path / "public/index.html").read_text()
    assert (tmp_path / "public/static/app.js").exists()
    assert (tmp_path / "vercel_entry.py").exists()
    assert "rapidocr" not in (tmp_path / "requirements.txt").read_text()
