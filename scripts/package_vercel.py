"""Stage only public application files; no environment files or local databases."""

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps/api"


def package(destination):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths = list((API / "app").rglob("*.py"))
    paths += [p for p in (API / "app/static").rglob("*") if p.is_file() and p.suffix in {".html", ".css", ".js", ".pdf", ".svg", ".png", ".jpg", ".ico"}]
    paths += [API / "vercel_entry.py", API / "vercel.json"]
    for source in paths:
        if "__pycache__" in source.parts:
            continue
        target = destination / source.relative_to(API)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    shutil.copy2(API / "requirements-demo.txt", destination / "requirements.txt")
    dependencies = [line.strip() for line in (API / "requirements-demo.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    (destination / "pyproject.toml").write_text(
        '[project]\nname = "knowra"\nversion = "2.0.0"\nrequires-python = ">=3.12,<3.13"\n'
        + 'dependencies = ' + json.dumps(dependencies) + '\n\n'
        '[tool.vercel]\nentrypoint = "vercel_entry:app"\n', encoding="utf-8")
    public = destination / "public"
    public.mkdir(exist_ok=True)
    shutil.copytree(API / "app/static", public / "static", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    html = (API / "app/static/index.html").read_text(encoding="utf-8")
    html = html.replace('id="auth" class="auth-layout"', 'id="auth" class="auth-layout hidden"')
    html = html.replace('id="demo-loading" class="loading hidden"', 'id="demo-loading" class="loading"')
    (public / "index.html").write_text(html, encoding="utf-8")
    (destination / ".vercelignore").write_text('.env\n.env.*\n__pycache__\n**/__pycache__\n*.pyc\n', encoding="utf-8")
    return len(paths)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "output/vercel-knowra")
    args = parser.parse_args()
    print(f"Staged {package(args.output)} public application files in {args.output}")
