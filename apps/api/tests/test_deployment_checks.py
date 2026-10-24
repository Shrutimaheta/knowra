import importlib.util
import json
from pathlib import Path


def checker():
    path = Path(__file__).resolve().parents[3] / "scripts/check_deployment.py"
    spec = importlib.util.spec_from_file_location("deployment_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_check(monkeypatch, records):
    module = checker()

    def command(arguments):
        if arguments[0] == "ps":
            return json.dumps(records)
        return json.dumps({"alerts": [], "status": "ok"})

    monkeypatch.setattr(module, "command", command)
    return module.main()


def services():
    return [{"Service": name, "State": "running", "Health": "healthy"}
            for name in ("api", "worker", "db", "proxy", "parser", "clamav", "backup")]


def test_completed_migration_does_not_fail_operational_check(monkeypatch):
    records = services() + [{"Service": "migrate", "State": "exited", "ExitCode": 0}]
    assert run_check(monkeypatch, records) == 0


def test_starting_service_and_public_database_are_not_reported_healthy(monkeypatch):
    records = services()
    records[0]["Health"] = "starting"
    assert run_check(monkeypatch, records) == 1
    records = services()
    records[2]["Publishers"] = [{"PublishedPort": 5432}]
    assert run_check(monkeypatch, records) == 1
