"""Bounded HTTP smoke load against an isolated, disposable local server/database."""

import asyncio
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


async def run(base, cookies):
    limits = httpx.Limits(max_connections=5)
    async with httpx.AsyncClient(
        base_url=base, cookies=cookies, limits=limits, timeout=30
    ) as client:

        async def request(index):
            started = time.perf_counter()
            result = await client.post(
                "/api/v1/search",
                json={
                    "content": [
                        "leave policy",
                        "security requirements",
                        "customer onboarding",
                    ][index % 3]
                },
            )
            return {
                "status": result.status_code,
                "latency_ms": (time.perf_counter() - started) * 1000,
            }

        semaphore = asyncio.Semaphore(5)

        async def limited(index):
            async with semaphore:
                return await request(index)

        return await asyncio.gather(*(limited(i) for i in range(50)))


def main():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="knowra-load-") as temp:
        env = os.environ.copy()
        env.pop("DATABASE_URL", None)
        env.update(
            KNOWRA_DB=str(Path(temp) / "load.db"),
            EMBEDDED_WORKER="false",
            EAGER_INGESTION="true",
            EMBEDDING_MODEL="",
            APP_ENV="development",
            COOKIE_SECURE="false",
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                str(ROOT / "apps/api"),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx.Client(base_url=base, timeout=10) as client:
                deadline = time.monotonic() + 30
                while True:
                    try:
                        if client.get("/api/v1/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Load-test server failed to start")
                    time.sleep(0.2)
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": "load@example.test",
                        "name": "Load Test",
                        "workspace": "Disposable test workspace",
                        "password": "load-test-only-password",
                    },
                ).raise_for_status()
                client.post("/api/v1/demo/seed").raise_for_status()
                # The response may arrive before its background ingestion finishes.
                # Measure ready-source searches, not the intentional indexing guard.
                deadline = time.monotonic() + 30
                while True:
                    response = client.get("/api/v1/documents")
                    response.raise_for_status()
                    documents = response.json()
                    if documents and all(d["status"] == "ready" for d in documents):
                        break
                    if any(d["status"] == "failed" for d in documents):
                        raise RuntimeError("Load fixture ingestion failed")
                    if time.monotonic() > deadline:
                        raise RuntimeError("Load fixture ingestion did not finish")
                    time.sleep(0.1)
                results = asyncio.run(run(base, dict(client.cookies)))
            latencies = sorted(r["latency_ms"] for r in results)
            report = {
                "requests": len(results),
                "concurrency": 5,
                "errors": sum(r["status"] != 200 for r in results),
                "status_counts": dict(Counter(r["status"] for r in results)),
                "p50_ms": round(statistics.median(latencies), 2),
                "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 2),
                "scope": "Local smoke load with four fictional documents and keyword retrieval; not a capacity benchmark.",
            }
            (ROOT / "evals/load-report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2))
            if report["errors"]:
                raise RuntimeError("Load smoke failed")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
