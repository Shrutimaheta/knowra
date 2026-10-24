"""A bounded evidence graph made only from accessible, persisted relationships."""

import json

from app.security import current_user
from app.store import db
from fastapi import APIRouter, Depends, Query

router = APIRouter(prefix="/api/v1")


@router.get("/knowledge-map")
def knowledge_map(
    document_limit: int = Query(default=30, ge=1, le=50),
    answer_limit: int = Query(default=30, ge=1, le=50),
    user=Depends(current_user),
):
    with db() as c:
        permission = "org=? AND (visibility='workspace' OR owner=?)"
        document_count = c.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE " + permission,
            (user["org"], user["id"]),
        ).fetchone()["n"]
        documents = [
            dict(row)
            for row in c.execute(
                "SELECT id,title,version,status,visibility,created FROM documents WHERE "
                + permission
                + " ORDER BY created DESC,id LIMIT ?",
                (user["org"], user["id"], document_limit),
            )
        ]
        doc_lookup = {doc["id"]: doc for doc in documents}
        answer_count = c.execute(
            "SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.org=? AND c.user_id=? AND m.role='assistant'",
            (user["org"], user["id"]),
        ).fetchone()["n"]
        answers = [
            dict(row)
            for row in c.execute(
                "SELECT m.id,m.conversation,m.content,m.citations,m.created,m.model,c.title FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.org=? AND c.user_id=? AND m.role='assistant' ORDER BY m.created DESC,m.id LIMIT ?",
                (user["org"], user["id"], answer_limit),
            )
        ]
        if not documents:
            return {
                "nodes": [],
                "edges": [],
                "stats": {
                    "documents": 0,
                    "versions": 0,
                    "answers": 0,
                    "earlier_version_answers": 0,
                },
                "limited": bool(answer_count),
                "notice": "Upload a document to start your map. Links represent saved versions and citations, not inferred topic relationships.",
            }
        placeholders = ",".join("?" for _ in documents)
        versions = [
            dict(row)
            for row in c.execute(
                "SELECT id,document,number,filename,status,created FROM (SELECT id,document,number,filename,status,created,ROW_NUMBER() OVER (PARTITION BY document ORDER BY number DESC) AS rank FROM document_versions WHERE document IN ("
                + placeholders
                + ")) ranked WHERE rank<=3 ORDER BY number DESC,id",
                list(doc_lookup),
            )
        ]
        citations = {}
        referenced = set()
        for answer in answers:
            try:
                raw = json.loads(answer["citations"])
            except (ValueError, TypeError):
                raw = []
            safe = (
                [
                    item
                    for item in raw[:10]
                    if isinstance(item, dict)
                    and isinstance(item.get("document"), str)
                    and item.get("document") in doc_lookup
                    and isinstance(item.get("version_id"), str)
                ]
                if isinstance(raw, list)
                else []
            )
            citations[answer["id"]] = safe
            referenced.update(item["version_id"] for item in safe)
        if referenced:
            marks = ",".join("?" for _ in referenced)
            versions += [
                dict(row)
                for row in c.execute(
                    "SELECT id,document,number,filename,status,created FROM document_versions WHERE document IN ("
                    + placeholders
                    + ") AND id IN ("
                    + marks
                    + ")",
                    [*doc_lookup, *referenced],
                )
            ]
    by_id = {version["id"]: version for version in versions}
    current = {
        v["document"]: v
        for v in versions
        if v["number"] == doc_lookup[v["document"]]["version"]
    }
    ordered = [*current.values()]
    ordered += [by_id[id] for id in sorted(referenced) if id in by_id]
    ordered += versions
    selected = {}
    for version in ordered:
        if version["id"] in selected:
            continue
        if len(selected) >= 180:
            break
        selected[version["id"]] = version
    nodes, edges = [], []
    for doc in documents:
        nodes.append(
            {
                "id": "document:" + doc["id"],
                "type": "document",
                "label": doc["title"],
                "document": doc["id"],
                "current_version_id": current.get(doc["id"], {}).get("id"),
                "version": doc["version"],
                "status": doc["status"],
                "visibility": doc["visibility"],
            }
        )
    for version in selected.values():
        doc = doc_lookup[version["document"]]
        is_current = version["number"] == doc["version"]
        node_id = "version:" + version["id"]
        nodes.append(
            {
                "id": node_id,
                "type": "version",
                "label": f"v{version['number']} · {doc['title']}",
                "document": version["document"],
                "version_id": version["id"],
                "version": version["number"],
                "status": version["status"],
                "created": version["created"],
                "current": is_current,
                "current_version_id": current.get(doc["id"], {}).get("id"),
            }
        )
        edges.append(
            {
                "id": "version-link:" + version["id"],
                "source": "document:" + version["document"],
                "target": node_id,
                "type": "version",
                "historical": not is_current,
            }
        )
    earlier = 0
    for answer in answers:
        grouped = {}
        for citation in citations[answer["id"]]:
            version = selected.get(citation["version_id"])
            if not version or version["document"] != citation["document"]:
                continue
            page = citation.get("page")
            if type(page) is not int or not 1 <= page <= 300:
                continue
            grouped.setdefault(version["id"], []).append(
                {"page": page, "text": str(citation.get("content") or "")[:4000]}
            )
        if not grouped:
            continue
        answer_id = "answer:" + answer["id"]
        historical = any(
            selected[id]["number"] != doc_lookup[selected[id]["document"]]["version"]
            for id in grouped
        )
        earlier += int(historical)
        nodes.append(
            {
                "id": answer_id,
                "type": "answer",
                "label": answer["title"],
                "conversation": answer["conversation"],
                "message": answer["id"],
                "preview": answer["content"][:3000],
                "model": answer["model"],
                "created": answer["created"],
                "historical": historical,
            }
        )
        for version_id, passages in grouped.items():
            version = selected[version_id]
            edges.append(
                {
                    "id": "citation:" + answer["id"] + ":" + version_id,
                    "type": "citation",
                    "source": "version:" + version_id,
                    "target": answer_id,
                    "document": version["document"],
                    "version_id": version_id,
                    "historical": version["number"]
                    != doc_lookup[version["document"]]["version"],
                    "evidence": passages,
                }
            )
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "documents": len(documents),
            "versions": len(selected),
            "answers": sum(node["type"] == "answer" for node in nodes),
            "earlier_version_answers": earlier,
        },
        "limited": document_count > len(documents)
        or answer_count > len(answers)
        or len(by_id) > len(selected),
        "notice": "Shows recent accessible documents, their latest three versions plus cited versions, and your own cited answers. Lines represent stored citations and version ownership, not inferred topic relationships. An earlier-version citation needs review; it does not prove the answer is outdated.",
    }
