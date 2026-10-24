"""Permission-checked conflict scans and personal review persistence."""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from app.conflicts import detect
from app.security import current_user
from app.store import db
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


class ConflictScan(BaseModel):
    documents: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        min_length=2, max_length=8
    )


class ConflictReview(BaseModel):
    left_version: str = Field(max_length=100)
    right_version: str = Field(max_length=100)
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["open", "authoritative", "dismissed"]
    preferred_version: str | None = Field(default=None, max_length=100)
    note: str = Field(default="", max_length=1000)


def snapshot(c, document, version):
    return {
        "document": document["id"],
        "title": document["title"],
        "version_id": version["id"],
        "version": version["number"],
        "filename": version["filename"],
        "uploaded": version["created"],
        "pages": json.loads(version["pages"]),
    }


def register_conflict_routes(app, permitted_document, audit):
    @app.post("/api/v1/conflicts/scan")
    def scan(body: ConflictScan, user=Depends(current_user)):
        if len(set(body.documents)) != len(body.documents):
            raise HTTPException(
                422, "Select different documents for a cross-document check."
            )
        sources = []
        with db() as c:
            for document_id in body.documents:
                document = permitted_document(c, document_id, user)
                version = c.execute(
                    "SELECT * FROM document_versions WHERE document=? AND number=?",
                    (document_id, document["version"]),
                ).fetchone()
                if (
                    document["status"] != "ready"
                    or not version
                    or version["status"] != "ready"
                ):
                    raise HTTPException(
                        409,
                        "All selected documents must finish indexing before scanning.",
                    )
                source = snapshot(c, document, version)
                if not any(page.strip() for page in source["pages"]):
                    raise HTTPException(
                        422,
                        "A selected document has no extracted text. Use visual analysis for images without readable text.",
                    )
                sources.append(source)
            result = detect(sources)
            fingerprints = [finding["id"] for finding in result["findings"]]
            reviews = {}
            if fingerprints:
                reviews = {
                    row["fingerprint"]: dict(row)
                    for row in c.execute(
                        "SELECT fingerprint,status,preferred_version,note,updated FROM conflict_reviews WHERE user_id=? AND org=? AND fingerprint IN ("
                        + ",".join("?" for _ in fingerprints)
                        + ")",
                        [user["id"], user["org"], *fingerprints],
                    )
                }
        for finding in result["findings"]:
            finding["review"] = reviews.get(
                finding["id"],
                {
                    "status": "open",
                    "preferred_version": None,
                    "note": "",
                    "updated": None,
                },
            )
        return result | {
            "documents": [
                {k: v for k, v in source.items() if k != "pages"} for source in sources
            ],
            "review_scope": "personal",
        }

    @app.post("/api/v1/conflicts/review")
    def review(body: ConflictReview, user=Depends(current_user)):
        if body.left_version == body.right_version:
            raise HTTPException(422, "A conflict needs two different sources.")
        if body.status == "authoritative" and body.preferred_version not in (
            body.left_version,
            body.right_version,
        ):
            raise HTTPException(
                422, "Choose one of these two source versions as authoritative."
            )
        if body.status != "authoritative" and body.preferred_version is not None:
            raise HTTPException(
                422, "Only an authoritative review can select a preferred source."
            )
        with db() as c:
            # Uploads also acquire this lock, so source versions cannot change
            # between the current-version check and the saved review decision.
            c.execute("UPDATE organizations SET name=name WHERE id=?", (user["org"],))
            sources = []
            for version_id in (body.left_version, body.right_version):
                version = c.execute(
                    "SELECT * FROM document_versions WHERE id=?", (version_id,)
                ).fetchone()
                if not version:
                    raise HTTPException(404, "Source version not found.")
                document = permitted_document(c, version["document"], user)
                if (
                    document["version"] != version["number"]
                    or document["status"] != "ready"
                    or version["status"] != "ready"
                ):
                    raise HTTPException(
                        409,
                        "A source changed or is still indexing. Run the scan again before saving a review.",
                    )
                sources.append(snapshot(c, document, version))
            if sources[0]["document"] == sources[1]["document"]:
                raise HTTPException(
                    422, "Use version comparison for versions of the same document."
                )
            findings = detect(sources, target=body.fingerprint)["findings"]
            if not any(finding["id"] == body.fingerprint for finding in findings):
                raise HTTPException(
                    409,
                    "This finding no longer matches the current sources. Run the scan again.",
                )
            updated = datetime.now(UTC).isoformat()
            c.execute(
                "INSERT INTO conflict_reviews (user_id,fingerprint,org,left_version,right_version,preferred_version,status,note,updated) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,fingerprint) DO UPDATE SET preferred_version=excluded.preferred_version,status=excluded.status,note=excluded.note,updated=excluded.updated",
                (
                    user["id"],
                    body.fingerprint,
                    user["org"],
                    body.left_version,
                    body.right_version,
                    body.preferred_version,
                    body.status,
                    body.note.strip(),
                    updated,
                ),
            )
            audit(c, user, "conflict.reviewed", body.fingerprint)
        return {
            "status": body.status,
            "preferred_version": body.preferred_version,
            "note": body.note.strip(),
            "updated": updated,
            "scope": "personal",
        }
