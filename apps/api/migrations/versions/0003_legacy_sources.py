"""Preserve existing source text and attach legacy chunks to immutable versions."""

import hashlib
import json
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"


def upgrade():
    c = op.get_bind()
    for row in c.execute(sa.text("SELECT * FROM documents")).mappings():
        version = str(uuid4())
        pages = {}
        for chunk in c.execute(
            sa.text(
                "SELECT page,content FROM chunks WHERE document=:document ORDER BY page"
            ),
            {"document": row["id"]},
        ).mappings():
            words = chunk["content"].split()
            previous = pages.setdefault(chunk["page"], [])
            overlap = next(
                (
                    size
                    for size in range(min(len(previous), len(words), 40), 0, -1)
                    if previous[-size:] == words[:size]
                ),
                0,
            )
            previous.extend(words[overlap:])
        extracted = (
            [
                " ".join(pages.get(number, []))
                for number in range(1, max(pages, default=1) + 1)
            ]
            if pages
            else [row["content"]]
        )
        c.execute(
            sa.text(
                "INSERT INTO document_versions (id,document,number,filename,checksum,pages,status,created) VALUES (:id,:document,:number,:filename,:checksum,:pages,:status,:created)"
            ),
            {
                "id": version,
                "document": row["id"],
                "number": row["version"] or 1,
                "filename": row["title"],
                "checksum": hashlib.sha256(row["content"].encode()).hexdigest(),
                "pages": json.dumps(extracted),
                "status": "ready" if row["status"] == "ready" else "queued",
                "created": row["created"],
            },
        )
        c.execute(
            sa.text("UPDATE chunks SET version_id=:version WHERE document=:document"),
            {"version": version, "document": row["id"]},
        )
        if row["status"] != "ready":
            c.execute(
                sa.text(
                    "INSERT INTO ingestion_jobs (id,version_id,status,attempts,available) VALUES (:id,:version,'queued',0,0)"
                ),
                {"id": str(uuid4()), "version": version},
            )
    for message in c.execute(sa.text("SELECT id,citations FROM messages")).mappings():
        sources = json.loads(message["citations"])
        for index, source in enumerate(sources, 1):
            version = (
                c.execute(
                    sa.text(
                        "SELECT id,number FROM document_versions WHERE document=:document ORDER BY number DESC LIMIT 1"
                    ),
                    {"document": source["document"]},
                )
                .mappings()
                .first()
            )
            if version:
                source.update(
                    version_id=version["id"],
                    version=version["number"],
                    citation_number=index,
                )
        c.execute(
            sa.text("UPDATE messages SET citations=:sources WHERE id=:id"),
            {"sources": json.dumps(sources), "id": message["id"]},
        )
    if c.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
        op.execute("ALTER TABLE chunks ADD COLUMN vector_embedding vector(384)")
        op.execute(
            "CREATE INDEX chunks_keyword ON chunks USING gin (to_tsvector('english',content))"
        )
        op.execute(
            "CREATE INDEX chunks_semantic ON chunks USING hnsw (vector_embedding vector_cosine_ops)"
        )


def downgrade():
    raise RuntimeError(
        "Restore a backup rather than dropping immutable source history."
    )
