"""Read-only host acceptance check; never prints resolved Compose secrets."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.production.yaml", "-f", "compose.operations.yaml"]


def command(arguments):
    result = subprocess.run(COMPOSE + arguments, cwd=ROOT, capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Deployment command failed; inspect private host logs")
    return result.stdout


def main():
    try:
        output = command(["ps", "--format", "json"])
        records = json.loads(output) if output.lstrip().startswith("[") else [json.loads(line) for line in output.splitlines() if line.strip()]
        services = {item["Service"]: item for item in records}
        required = {"api", "worker", "db", "proxy", "parser", "clamav", "backup"}
        problems = sorted(required - services.keys())
        for name, item in services.items():
            if name not in required:
                continue
            if item.get("State") != "running" or item.get("Health", "") not in ("", "healthy"):
                problems.append(name + ":not_healthy")
            if name != "proxy" and item.get("Publishers"):
                if any(p.get("PublishedPort") for p in item["Publishers"]):
                    problems.append(name + ":public_port")
        operational = json.loads(command(["exec", "-T", "api", "python", "-c", "import json; from app.operations import status; print(json.dumps(status()))"]))
        problems.extend(operational["alerts"])
        print(json.dumps({"status": "attention" if problems else "ok", "problems": problems, "operations": operational}, indent=2))
        return int(bool(problems))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        print("Deployment verification unavailable. Docker, a configured deployment and private host logs are required.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
