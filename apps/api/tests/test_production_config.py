import pytest
from app.config import validate_runtime


@pytest.fixture
def production(monkeypatch):
    settings = {
        "APP_ENV": "production",
        "PUBLIC_URL": "https://knowra.example.com",
        "COOKIE_SECURE": "true",
        "DATABASE_URL": "postgresql+psycopg://knowra_app:test-secret@db/knowra",
        "AUTO_MIGRATE": "false",
        "EMBEDDED_WORKER": "false",
        "SMTP_HOST": "smtp.example.com",
        "SMTP_FROM": "Knowra <hello@example.com>",
        "SMTP_USER": "",
        "SMTP_PASSWORD": "",
        "CLAMAV_HOST": "clamav",
        "PARSER_URL": "http://parser:8001",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)


def test_complete_production_configuration(production):
    validate_runtime()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PUBLIC_URL", "https://"),
        ("PUBLIC_URL", "https://user:secret@example.com"),
        ("PUBLIC_URL", "https://example.com/path"),
        ("PUBLIC_URL", "http://example.com"),
        ("COOKIE_SECURE", "false"),
        ("DATABASE_URL", "sqlite:///data.db"),
        ("DATABASE_URL", "postgresql://user:replace_with_password@db/knowra"),
        ("AUTO_MIGRATE", "true"),
        ("EMBEDDED_WORKER", "true"),
        ("SMTP_HOST", ""),
        ("SMTP_USER", "username-without-password"),
        ("CLAMAV_HOST", ""),
        ("PARSER_URL", ""),
    ],
)
def test_unsafe_production_configuration_rejected(production, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError, match="Production configuration") as error:
        validate_runtime()
    assert "test-secret" not in str(error.value)
    assert "user:secret" not in str(error.value)


def test_development_remains_available(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    validate_runtime()
