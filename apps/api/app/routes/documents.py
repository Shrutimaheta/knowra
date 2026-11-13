"""Document upload, versions, sources, comparison and conflict reviews."""

import json
import os
import time
from pathlib import Path

from app.conflict_routes import register_conflict_routes
from app.extraction import visual_file
from app.malware import scan
from app.object_storage import original as stored_original
from app.processing import validate
from app.routes.common import audit, now, permitted_document, uid
from app.security import admin, current_user
from app.store import db
from app.worker import enqueue, run_once
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field

router = APIRouter()


register_conflict_routes(router, permitted_document, audit)


@router.get("/api/v1/documents/{document_id}/versions/{version_id}/integrity")
def integrity(document_id: str, version_id: str, user=Depends(current_user)):
    from app.neon_functions import source_integrity

    with db() as c:
        permitted_document(c, document_id, user)
        if not c.execute("SELECT id FROM document_versions WHERE id=? AND document=?", (version_id, document_id)).fetchone():
            raise HTTPException(404, "Source version not found.")
    return source_integrity(document_id, version_id, user)


def check_upload(file):
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Files must be 10 MB or smaller.")
    title = (file.filename or "document").replace("\\", "/").split("/")[-1][:200]
    scan(data)
    return data, title, validate(title, data)


def upload_quota(c, user, size):
    # Serialize workspace writes across API instances for atomic quota enforcement.
    c.execute("UPDATE organizations SET name=name WHERE id=?", (user["org"],))
    total = c.execute(
        "SELECT COALESCE(SUM(COALESCE(v.original_size,length(v.original))),0) AS total FROM document_versions v JOIN documents d ON d.id=v.document WHERE d.org=?",
        (user["org"],),
    ).fetchone()["total"]
    if total + size > int(os.getenv("WORKSPACE_STORAGE_MB", "100")) * 1024 * 1024:
        raise HTTPException(
            413,
            "Workspace storage quota reached. Remove unused documents or contact your administrator.",
        )


@router.post("/api/v1/documents", status_code=201)
def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form("General"),
    visibility: str = Form("workspace"),
    user=Depends(current_user),
):
    if user["role"] == "viewer":
        raise HTTPException(403, "Viewers cannot upload documents.")
    if visibility not in ("workspace", "private") or len(category) > 60:
        raise HTTPException(422, "Invalid document settings.")
    data, title, pages = check_upload(file)
    document_id = uid()
    with db() as c:
        upload_quota(c, user, len(data))
        count = c.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE org=?", (user["org"],)
        ).fetchone()["n"]
        if count >= int(os.getenv("WORKSPACE_DOCUMENT_LIMIT", "500")):
            raise HTTPException(413, "Workspace document quota reached.")
        c.execute(
            "INSERT INTO documents (id,org,owner,title,category,visibility,status,content,created) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                document_id,
                user["org"],
                user["id"],
                title,
                category,
                visibility,
                "processing",
                "",
                now(),
            ),
        )
        version = enqueue(c, document_id, title, data, pages, 1)
        audit(c, user, "document.uploaded", document_id)
    if os.getenv("EAGER_INGESTION", "false") == "true":
        background.add_task(run_once, version)
    return {"id": document_id, "version_id": version, "status": "processing"}


@router.post("/api/v1/documents/{document_id}/versions", status_code=201)
def upload_version(
    document_id: str,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(current_user),
):
    data, title, pages = check_upload(file)
    with db() as c:
        upload_quota(c, user, len(data))
        doc = permitted_document(c, document_id, user)
        if user["role"] == "viewer" or (
            doc["owner"] != user["id"] and user["role"] not in ("owner", "admin")
        ):
            raise HTTPException(
                403, "Only the document owner or an administrator can add versions."
            )
        number = doc["version"] + 1
        c.execute(
            "UPDATE documents SET version=?,status='processing',error=NULL WHERE id=?",
            (number, document_id),
        )
        version = enqueue(c, document_id, title, data, pages, number)
        audit(c, user, "document.version_uploaded", document_id)
    if os.getenv("EAGER_INGESTION", "false") == "true":
        background.add_task(run_once, version)
    return {
        "id": document_id,
        "version_id": version,
        "version": number,
        "status": "processing",
    }


@router.get("/api/v1/documents/{document_id}/versions")
def versions(document_id: str, user=Depends(current_user)):
    with db() as c:
        permitted_document(c, document_id, user)
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,number,filename,checksum,status,created FROM document_versions WHERE document=? ORDER BY number DESC",
                (document_id,),
            )
        ]


@router.get("/api/v1/documents/{document_id}/versions/{version_id}")
def version_detail(document_id: str, version_id: str, user=Depends(current_user)):
    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT id,number,filename,pages,layout_meta,status,checksum FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        return dict(version) | {
            "pages": json.loads(version["pages"]),
            "layout_meta": json.loads(version["layout_meta"]),
        }


@router.get("/api/v1/documents/{document_id}/versions/{version_id}/pages/{number}/image")
def source_image(
    document_id: str, version_id: str, number: int, user=Depends(current_user)
):
    from app.extraction import ExtractionError
    from app.processing import page_image

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT original,original_key,filename FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if (
            not version
            or (version["original"] is None and not version["original_key"])
            or not visual_file(version["filename"])
        ):
            raise HTTPException(404, "PDF or image source not found.")
        source = dict(version)
    data = stored_original(source)
    try:
        image = page_image(data, number)
    except ExtractionError as error:
        raise HTTPException(404, str(error)) from None
    return Response(
        image, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.get("/api/v1/documents/{document_id}/compare")
def compare_versions(
    document_id: str, from_version: str, to_version: str, user=Depends(current_user)
):
    from app.comparison import compare_pages

    if from_version == to_version:
        raise HTTPException(422, "Choose two different versions.")
    with db() as c:
        document = permitted_document(c, document_id, user)
        selected = []
        for version_id in (from_version, to_version):
            version = c.execute(
                "SELECT id,number,filename,pages,status FROM document_versions WHERE id=? AND document=?",
                (version_id, document_id),
            ).fetchone()
            if not version:
                raise HTTPException(404, "Source version not found.")
            if version["status"] != "ready":
                raise HTTPException(
                    409, "Both versions must finish indexing before comparison."
                )
            selected.append(dict(version))
    if not any(p.strip() for p in json.loads(selected[0]["pages"])) or not any(
        p.strip() for p in json.loads(selected[1]["pages"])
    ):
        raise HTTPException(
            422,
            "Both versions need extracted text to compare. Use visual analysis for images without readable text.",
        )
    result = compare_pages(*[json.loads(v["pages"]) for v in selected])
    return result | {
        "document": document_id,
        "title": document["title"],
        "before": {k: v for k, v in selected[0].items() if k != "pages"},
        "after": {k: v for k, v in selected[1].items() if k != "pages"},
    }


class EvidenceRequest(BaseModel):
    page: int = Field(ge=1, le=300)
    text: str = Field(min_length=1, max_length=4000)


@router.post("/api/v1/documents/{document_id}/versions/{version_id}/evidence")
def source_evidence(
    document_id: str, version_id: str, body: EvidenceRequest, user=Depends(current_user)
):
    from app.processing import highlight

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT pages,original,original_key,filename,status FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        if version["status"] != "ready":
            raise HTTPException(409, "Wait for this version to finish indexing.")
        pages = json.loads(version["pages"])
        if body.page > len(pages):
            raise HTTPException(404, "Source page not found.")
        if len(pages[body.page - 1]) > 100_000:
            raise HTTPException(
                413,
                "This page is too large to highlight. Open the original source instead.",
            )
        source = dict(version)
    data = stored_original(source) if visual_file(source["filename"]) else None
    return highlight(pages, body.page, body.text, data)


@router.get("/api/v1/documents/{document_id}/versions/{version_id}/original")
def original(document_id: str, version_id: str, user=Depends(current_user)):
    from urllib.parse import quote

    with db() as c:
        permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT original,original_key,filename,pages FROM document_versions WHERE id=? AND document=?",
            (version_id, document_id),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        data = stored_original(dict(version))
        filename = version["filename"]
        if data is None:
            data = "\n\n".join(json.loads(version["pages"])).encode()
            filename += ".legacy-extract.txt"
        media = (
            "application/pdf"
            if filename.lower().endswith(".pdf")
            else {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(Path(filename).suffix.lower(), "text/plain; charset=utf-8")
        )
        return Response(
            bytes(data),
            media_type=media,
            headers={
                "Content-Disposition": "inline; filename*=UTF-8''"
                + quote(filename, safe=""),
                "Cache-Control": "no-store",
            },
        )


@router.post("/api/v1/documents/{document_id}/retry")
def retry_document(document_id: str, user=Depends(current_user)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        if user["role"] == "viewer" or (
            doc["owner"] != user["id"] and user["role"] not in ("owner", "admin")
        ):
            raise HTTPException(
                403, "Only the owner or an administrator can retry indexing."
            )
        job = c.execute(
            "SELECT j.* FROM ingestion_jobs j JOIN document_versions v ON v.id=j.version_id WHERE v.document=? AND v.number=?",
            (document_id, doc["version"]),
        ).fetchone()
        if not job or job["status"] != "failed":
            raise HTTPException(409, "Only failed jobs can be retried.")
        c.execute(
            "UPDATE ingestion_jobs SET status='queued',attempts=0,available=?,lease_until=NULL,lease_token=NULL,error=NULL WHERE id=?",
            (time.time(), job["id"]),
        )
        c.execute(
            "UPDATE documents SET status='processing',error=NULL WHERE id=?",
            (document_id,),
        )
        c.execute(
            "UPDATE document_versions SET status='queued' WHERE id=?",
            (job["version_id"],),
        )
        audit(c, user, "document.retry", document_id)
    return {"ok": True}


@router.get("/api/v1/documents")
def documents(user=Depends(current_user)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT id,title,category,visibility,status,error,created,version FROM documents WHERE org=? AND (visibility='workspace' OR owner=?) ORDER BY created DESC",
                (user["org"], user["id"]),
            )
        ]


@router.get("/api/v1/documents/{document_id}")
def document(document_id: str, user=Depends(current_user)):
    with db() as c:
        return permitted_document(c, document_id, user)


@router.delete("/api/v1/documents/{document_id}")
def delete_document(document_id: str, user=Depends(current_user)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        if doc["owner"] != user["id"] and user["role"] not in ("owner", "admin"):
            raise HTTPException(
                403, "Only the owner or an administrator can delete this document."
            )
        c.execute("DELETE FROM documents WHERE id=?", (document_id,))
        audit(c, user, "document.deleted", document_id)
    return {"ok": True}


@router.post("/api/v1/documents/{document_id}/reindex")
def reindex(document_id: str, user=Depends(admin)):
    with db() as c:
        doc = permitted_document(c, document_id, user)
        version = c.execute(
            "SELECT id FROM document_versions WHERE document=? AND number=?",
            (document_id, doc["version"]),
        ).fetchone()
        if not version:
            raise HTTPException(404, "Source version not found.")
        job = c.execute(
            "SELECT id,status FROM ingestion_jobs WHERE version_id=?", (version["id"],)
        ).fetchone()
        if job and job["status"] in ("queued", "running"):
            raise HTTPException(409, "This document is already queued or processing.")
        if job:
            c.execute(
                "UPDATE ingestion_jobs SET status='queued',attempts=0,available=?,lease_until=NULL,lease_token=NULL,error=NULL WHERE id=?",
                (time.time(), job["id"]),
            )
        else:
            c.execute(
                "INSERT INTO ingestion_jobs (id,version_id,status,attempts,available) VALUES (?,?,'queued',0,?)",
                (uid(), version["id"], time.time()),
            )
        c.execute(
            "UPDATE documents SET status='processing',error=NULL WHERE id=?",
            (document_id,),
        )
        c.execute(
            "UPDATE document_versions SET status='queued' WHERE id=?", (version["id"],)
        )
        audit(c, user, "document.reindex", document_id)
    return {"ok": True}
