"""Database-backed ingestion queue with atomic leases, bounded retries and recovery."""

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.embeddings import encode, model_name
from app.extraction import IMAGE_EXTENSIONS, ExtractionError
from app.malware import scan
from app.object_storage import enabled as storage_enabled
from app.object_storage import original as stored_original
from app.object_storage import put as store_original
from app.processing import extract
from app.rag import chunk_pages
from app.store import db, engine, initialize
from fastapi import HTTPException

log = logging.getLogger("knowra.worker")
MAX_ATTEMPTS = 3


def enqueue(c, document, filename, original, pages, number):
    version = str(uuid4())
    key = store_original(version, original) if storage_enabled() else None
    c.execute(
        "INSERT INTO document_versions (id,document,number,filename,original,checksum,pages,status,created,original_key,original_size) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            version,
            document,
            number,
            filename,
            None if key else original,
            hashlib.sha256(original).hexdigest(),
            json.dumps(pages),
            "queued",
            datetime.now(UTC).isoformat(),
            key,
            len(original),
        ),
    )
    c.execute(
        "INSERT INTO ingestion_jobs (id,version_id,status,attempts,available) VALUES (?,?,'queued',0,?)",
        (str(uuid4()), version, time.time()),
    )
    return version


def run_once(version_id=None):
    now = time.time()
    with db() as c:
        # Expired leases at the retry limit become visible failures, never stuck jobs.
        exhausted = c.execute(
            "SELECT version_id FROM ingestion_jobs WHERE status='running' AND lease_until<? AND attempts>=?",
            (now, MAX_ATTEMPTS),
        ).fetchall()
        for row in exhausted:
            c.execute(
                "UPDATE ingestion_jobs SET status='failed',error='Worker lease expired at retry limit' WHERE version_id=? AND lease_until<?",
                (row["version_id"], now),
            )
            c.execute(
                "UPDATE document_versions SET status='failed' WHERE id=?",
                (row["version_id"],),
            )
            c.execute(
                "UPDATE documents SET status='failed',error='Processing interrupted. Retry from the library.' WHERE id IN (SELECT document FROM document_versions WHERE id=? AND number=documents.version)",
                (row["version_id"],),
            )
        query = "SELECT * FROM ingestion_jobs WHERE attempts<? AND ((status='queued' AND available<=?) OR (status='running' AND lease_until<?))"
        values = [MAX_ATTEMPTS, now, now]
        if version_id:
            query += " AND version_id=?"
            values.append(version_id)
        job = c.execute(query + " ORDER BY available LIMIT 1", values).fetchone()
        if not job:
            return False
        token = str(uuid4())
        claimed = c.execute(
            "UPDATE ingestion_jobs SET status='running',attempts=attempts+1,lease_until=?,lease_token=? WHERE id=? AND attempts=? AND ((status='queued' AND available<=?) OR (status='running' AND lease_until<?)) RETURNING id",
            (now + 900, token, job["id"], job["attempts"], now, now),
        ).fetchone()
        if not claimed:
            return False
        version = c.execute(
            "SELECT * FROM document_versions WHERE id=?", (job["version_id"],)
        ).fetchone()
        if not version:
            return True
    try:
        pages, layout = json.loads(version["pages"]), []
        original = stored_original(dict(version))
        if original is not None:
            scan(original)
            if version["filename"].lower().endswith((".pdf", *IMAGE_EXTENSIONS)):
                pages, layout = extract(version["filename"], original, pages)
        passages = list(chunk_pages(pages))
        vectors = encode([content for _, content in passages]) if passages else []
        with db() as c:
            live = c.execute(
                "SELECT id FROM ingestion_jobs WHERE id=? AND lease_token=? AND status='running'",
                (job["id"], token),
            ).fetchone()
            if not live:
                return True
            c.execute("DELETE FROM chunks WHERE version_id=?", (version["id"],))
            for (page, content), vector in zip(passages, vectors, strict=True):
                chunk_id = str(uuid4())
                serialized = json.dumps(vector) if vector is not None else None
                c.execute(
                    "INSERT INTO chunks (id,document,content,page,version_id,embedding,embedding_model) VALUES (?,?,?,?,?,?,?)",
                    (
                        chunk_id,
                        version["document"],
                        content,
                        page,
                        version["id"],
                        serialized,
                        model_name() or None,
                    ),
                )
                if vector is not None and engine().dialect.name == "postgresql":
                    if len(vector) != 384:
                        raise ValueError(
                            "The PostgreSQL vector index expects a 384-dimensional model"
                        )
                    c.execute(
                        "UPDATE chunks SET vector_embedding=CAST(? AS vector) WHERE id=?",
                        (serialized, chunk_id),
                    )
            c.execute(
                "UPDATE document_versions SET status='ready',pages=?,layout_meta=? WHERE id=?",
                (json.dumps(pages), json.dumps(layout), version["id"]),
            )
            c.execute(
                "UPDATE documents SET status='ready',error=NULL,content=? WHERE id=? AND version=?",
                (
                    "\n\n".join(pages),
                    version["document"],
                    version["number"],
                ),
            )
            c.execute(
                "UPDATE ingestion_jobs SET status='complete',lease_until=NULL,lease_token=NULL,error=NULL WHERE id=? AND lease_token=?",
                (job["id"], token),
            )
    except Exception as error:
        log.exception("Ingestion job %s failed", job["id"])
        attempt = job["attempts"] + 1
        with db() as c:
            live = c.execute(
                "SELECT id FROM ingestion_jobs WHERE id=? AND lease_token=? AND status='running'",
                (job["id"], token),
            ).fetchone()
            if live:
                permanent = isinstance(error, ExtractionError) or (
                    isinstance(error, HTTPException) and error.status_code == 400
                )
                status = (
                    "failed"
                    if attempt >= MAX_ATTEMPTS or permanent
                    else "queued"
                )
                detail = (
                    str(error)
                    if isinstance(error, ExtractionError)
                    else error.detail
                    if isinstance(error, HTTPException) and error.status_code == 400
                    else "Indexing failed; check worker logs and model configuration."
                )
                c.execute(
                    "UPDATE ingestion_jobs SET status=?,available=?,lease_until=NULL,lease_token=NULL,error=? WHERE id=? AND lease_token=?",
                    (
                        status,
                        time.time() + min(60, 2**attempt),
                        detail,
                        job["id"],
                        token,
                    ),
                )
                c.execute(
                    "UPDATE document_versions SET status=? WHERE id=?",
                    (status, version["id"]),
                )
                c.execute(
                    "UPDATE documents SET status=?,error=? WHERE id=? AND version=?",
                    (
                        "failed" if status == "failed" else "processing",
                        "Indexing failed; automatic retry scheduled."
                        if status == "queued"
                        else detail,
                        version["document"],
                        version["number"],
                    ),
                )
    return True


def loop(stop):
    while not stop.is_set():
        try:
            processed = run_once()
            if heartbeat := os.getenv("WORKER_HEARTBEAT"):
                Path(heartbeat).touch()
            if processed:
                continue
        except Exception:
            log.exception("Worker poll failed")
        stop.wait(1)


if __name__ == "__main__":
    import threading

    from app.config import validate_runtime

    logging.basicConfig(level=logging.INFO)
    validate_runtime()
    if os.getenv("AUTO_MIGRATE", "true") == "true":
        initialize()
    try:
        loop(threading.Event())
    except KeyboardInterrupt:
        pass
