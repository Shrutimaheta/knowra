"""Allowlisted source bundle: never includes .env, workspaces, backups or screenshots."""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def package(destination):
    files = [ROOT / "render.yaml", ROOT / "docs/render-demo.md", ROOT / "docs/demo-documents.md"]
    api = ROOT / "apps/api"
    files += [api / name for name in ("Dockerfile.demo", "requirements-demo.txt", "alembic.ini", ".dockerignore")]
    files += list((api / "app").rglob("*.py")) + list((api / "migrations").rglob("*.py"))
    files += [path for path in (api / "app/static").rglob("*") if path.suffix in (".html", ".css", ".js")]
    files += [api / f"app/static/demo/policy-{year}.pdf" for year in (2025, 2026)]
    sys.path.insert(0, str(api))
    from app.demo_catalog import DIRECTORY, PDF_NAMES

    files += [DIRECTORY / name for name in PDF_NAMES]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.md", (ROOT / "docs/render-demo.md").read_text(encoding="utf-8"))
        for path in sorted(set(files)):
            if "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(ROOT).as_posix())
    return len(files)


if __name__ == "__main__":
    target = ROOT / "dist/knowra-render-demo.zip"
    print(f"Prepared {package(target)} allowlisted files: {target}")
