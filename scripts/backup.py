"""Portable backup format; operators must protect it with encryption; restore only to an empty database.

Usage: python scripts/backup.py backup path.json.gz
       KNOWRA_DB=<new path> python scripts/backup.py restore path.json.gz
"""

import argparse
import base64
import gzip
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import MetaData, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.store import engine, initialize


def encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__binary__": base64.b64encode(value).decode()}
    return value


def decode(value):
    return (
        base64.b64decode(value["__binary__"])
        if isinstance(value, dict) and "__binary__" in value
        else value
    )


def backup(path):
    if path.exists():
        raise ValueError("Backup already exists; choose a new filename.")
    metadata = MetaData()
    metadata.reflect(bind=engine())
    tables = {}
    with engine().connect() as c:
        if c.dialect.name == "postgresql":
            c = c.execution_options(isolation_level="REPEATABLE READ")
        with c.begin():
            for table in metadata.sorted_tables:
                records = []
                for row in c.execute(select(table)).mappings():
                    values = dict(row)
                    if table.name == "document_versions" and values.get("original_key"):
                        from app.object_storage import get

                        values["original"] = get(values["original_key"])
                        values["original_key"] = None
                    records.append({key: encode(value) for key, value in values.items()})
                tables[table.name] = records
    payload = {
        "format": "knowra-backup-v1",
        "created": datetime.now(UTC).isoformat(),
        "tables": tables,
    }
    # Exclusive creation prevents accidentally overwriting a prior recovery point.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb") as f:
        f.write(json.dumps(payload).encode())
    print("Backup created:", path)


def restore(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("format") != "knowra-backup-v1":
        raise ValueError("Unsupported backup format")
    initialize()
    metadata = MetaData()
    metadata.reflect(bind=engine())
    with engine().begin() as c:
        existing = (
            c.execute(select(metadata.tables["alembic_version"])).mappings().first()
        )
        backed = payload["tables"].get("alembic_version", [])
        if not backed or existing["version_num"] != backed[0]["version_num"]:
            raise ValueError(
                "Restore using the same application migration revision as the backup"
            )
        for table in metadata.sorted_tables:
            if (
                table.name != "alembic_version"
                and c.execute(select(table).limit(1)).first()
            ):
                raise ValueError(
                    "Restore target must be empty. Existing data will never be overwritten."
                )
        for table in metadata.sorted_tables:
            if table.name == "alembic_version":
                continue
            rows = [
                {
                    key: decode(value)
                    for key, value in row.items()
                    if key in table.columns
                }
                for row in payload["tables"].get(table.name, [])
            ]
            if rows:
                c.execute(table.insert(), rows)
    from sqlalchemy import text

    with engine().begin() as c:
        c.execute(text("DELETE FROM request_limits"))
        c.execute(text("DELETE FROM chat_runs"))
        c.execute(
            text(
                "UPDATE ingestion_jobs SET status='queued',lease_until=NULL,lease_token=NULL WHERE status='running'"
            )
        )
        if c.dialect.name == "postgresql":
            c.execute(
                text(
                    "UPDATE chunks SET vector_embedding=CAST(embedding AS vector) WHERE embedding IS NOT NULL"
                )
            )
    print("Restore completed into empty database")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    (backup if args.action == "backup" else restore)(args.path)
