"""Internal-only parser supervisor. No database, mail or AI credentials required."""

import json
import os
import site
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
slot = threading.BoundedSemaphore(1)
MAX_REQUEST = 18 * 1024 * 1024


def supervise(payload):
    if not slot.acquire(blocking=False):
        raise HTTPException(503, "Document processor is busy")
    try:
        with tempfile.TemporaryDirectory(prefix="knowra-parser-") as directory:
            output = Path(directory) / "result.json"
            # Never inherit application secrets into the parser child.
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "2",
                "OCR_MAX_PAGES": os.getenv("OCR_MAX_PAGES", "50"),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            if sys.platform == "win32":
                environment["PYTHONUSERBASE"] = site.getuserbase()
            result = subprocess.run(
                [sys.executable, "-m", "app.parser_job", str(output)],
                input=payload, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=environment, timeout=300, check=False,
            )
            if result.returncode or not output.exists() or output.stat().st_size > 32 * 1024 * 1024:
                raise HTTPException(422, "Document processing failed")
            return json.loads(output.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        raise HTTPException(422, "Document processing exceeded its time limit") from None
    finally:
        slot.release()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/process")
async def process(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST:
            raise HTTPException(413, "Document request too large")
    return await run_in_threadpool(supervise, bytes(body))
