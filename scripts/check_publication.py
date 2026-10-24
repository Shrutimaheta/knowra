"""Check the exact staged Git snapshot; never print matched credential values."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitignore", ".gitattributes", ".dockerignore", ".env.example",
    "README.md", "CONTRIBUTING.md", "SECURITY.md", "package.json",
    "package-lock.json", "tsconfig.json", "pytest.ini", "ruff.toml",
    "neon.ts", "hello.ts", "render.yaml", "compose.yaml",
    "compose.production.yaml", "compose.operations.yaml",
}
PUBLIC_DOCS = {
    "architecture.md", "deployment.md", "release-checklist.md",
    "render-demo.md", "free-hosting.md", "neon.md", "demo-documents.md",
}


def allowed(name):
    path = Path(name)
    if any(part in {"data", "__pycache__", "node_modules", ".git"} for part in path.parts):
        return False
    if name in ROOT_FILES or name in {"evals/retrieval.json", "evals/demo-corpus.json"}:
        return True
    if name.startswith("docs/"):
        return path.name in PUBLIC_DOCS and len(path.parts) == 2
    if name.startswith(".github/"):
        return path.suffix in {".yml", ".yaml", ".md"}
    if name.startswith("scripts/"):
        return path.suffix in {".py", ".ps1", ".mjs"}
    if name.startswith("web/"):
        return path.suffix == ".ts"
    if name.startswith("infrastructure/"):
        return path.suffix in {".sh", ".service", ".timer"} or path.name in {"Dockerfile", "Caddyfile"}
    if name.startswith("apps/api/"):
        if path.name in {"Dockerfile", "Dockerfile.demo", "alembic.ini", ".dockerignore"}:
            return len(path.parts) == 3
        if path.name.startswith("requirements") and path.suffix == ".txt":
            return len(path.parts) == 3
        if name.startswith(("apps/api/tests/", "apps/api/migrations/")):
            return path.suffix == ".py"
        if name.startswith("apps/api/app/"):
            if name.startswith("apps/api/app/static/demo/business/"):
                # Keep this list explicit; never publish arbitrary locally uploaded PDFs.
                from app.demo_catalog import PDF_NAMES

                return path.name in PDF_NAMES and len(path.parts) == 7
            return path.suffix in {".py", ".html", ".css", ".js"} or name in {
                "apps/api/app/static/demo/policy-2025.pdf",
                "apps/api/app/static/demo/policy-2026.pdf",
            }
    return False


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def private_values():
    """Compare local credentials/endpoints without including them in this report."""
    path = ROOT / ".env"
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip("\"'")
        sensitive = any(word in key for word in ("SECRET", "PASSWORD", "API_KEY", "DATABASE_URL", "ACCESS_KEY"))
        sensitive = sensitive or key.startswith("NEON_") and key.endswith(("URL", "URI"))
        if sensitive and len(value) >= 12 and "replace_with" not in value:
            result.append(value.encode())
    return result


def main():
    names = git("ls-files", "-z").decode().strip("\0").split("\0")
    if not names or names == [""]:
        print("FAIL: no staged repository files")
        return 1
    signatures = {
        "Google API credential": rb"AIza[0-9A-Za-z_-]{30,}",
        "GitHub credential": rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})",
        "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "AWS access key": rb"(?:AKIA|ASIA)[A-Z0-9]{16}",
        "provider credential": rb"(?:AQ\.[A-Za-z0-9_-]{30,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})",
    }
    secrets = private_values()
    context = ROOT / ".neon"
    if context.exists():
        secrets += [value.encode() for value in json.loads(context.read_text(encoding="utf-8-sig")).values()
                    if isinstance(value, str) and len(value) >= 12]
    problems = []
    total = 0
    for name in names:
        if not allowed(name):
            problems.append((name, "outside public file allowlist"))
            continue
        content = git("show", ":" + name)
        total += len(content)
        if len(content) > 5_000_000:
            problems.append((name, "unexpected large file"))
        for label, pattern in signatures.items():
            if re.search(pattern, content):
                problems.append((name, label))
        if any(value in content for value in secrets):
            problems.append((name, "matches private local configuration"))
    for name, reason in problems:
        print(f"FAIL: {name}: {reason}")
    if problems:
        return 1
    print(f"PUBLICATION CHECK PASSED: {len(names)} staged files, {total:,} bytes; allowlist and credential checks passed.")
    print("Excluded: private env/config, uploaded files, databases, backups, screenshots, caches and local reports.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "apps/api"))
    sys.exit(main())
