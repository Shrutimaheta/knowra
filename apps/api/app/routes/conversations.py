"""Search, conversations and streamed answers."""

import json
import logging
import os
import time

from app.demo import consume_question as consume_demo_question
from app.demo import enabled as demo_enabled
from app.embeddings import model_name, query_vector
from app.extraction import visual_file
from app.object_storage import original as stored_original
from app.providers import generation_provider
from app.rag import retrieve, single_topic_query, stream_answer, tokens
from app.routes.common import audit, now, permitted_document, uid
from app.security import current_user
from app.store import db, engine
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

router = APIRouter()


class Question(BaseModel):
    content: str = Field(min_length=1, max_length=3000)
    visual_document_id: str | None = Field(default=None, max_length=100)
    visual_page: int | None = Field(default=None, ge=1, le=300)


@router.post("/api/v1/search")
def search(body: Question, user=Depends(current_user)):
    query = body.content.strip()
    if not query:
        raise HTTPException(422, "Enter a search phrase.")
    with db() as c:
        pending = c.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE org=? AND status='processing' AND (visibility='workspace' OR owner=?)",
            (user["org"], user["id"]),
        ).fetchone()["n"]
        if pending:
            raise HTTPException(
                409,
                f"{pending} document(s) are still being indexed. Wait for Ready in the Knowledge library, then ask again.",
            )
        permitted = " FROM chunks ch JOIN documents d ON d.id=ch.document JOIN document_versions v ON v.id=ch.version_id WHERE d.org=? AND v.number=d.version AND v.status='ready' AND (d.visibility='workspace' OR d.owner=?)"
        select = "SELECT ch.id,ch.document,ch.content,ch.page,ch.version_id,ch.embedding,ch.embedding_model,d.title,v.number AS version"
        if engine().dialect.name == "postgresql":
            # Database-side keyword/vector candidates share the exact permission filter.
            keyword_query = " | ".join("'" + term.replace("'", "''") + "'" for term in list(dict.fromkeys(tokens(query)))[:64])
            rows = [
                dict(r)
                for r in c.execute(
                    select
                    + permitted
                    + " AND to_tsvector('english',ch.content) @@ to_tsquery('english',?) ORDER BY ts_rank_cd(to_tsvector('english',ch.content),to_tsquery('english',?)) DESC LIMIT 200",
                    (user["org"], user["id"], keyword_query, keyword_query),
                )
            ]
            semantic = []
            if model_name() and not (rows and single_topic_query(query)):
                vector = json.dumps(query_vector(query))
                semantic_rows = c.execute(
                    select
                    + ",1-(ch.vector_embedding <=> CAST(? AS vector)) AS similarity"
                    + permitted
                    + " AND ch.embedding_model=? AND ch.vector_embedding IS NOT NULL ORDER BY ch.vector_embedding <=> CAST(? AS vector) LIMIT 30",
                    (vector, user["org"], user["id"], model_name(), vector),
                ).fetchall()
                semantic = [
                    (r["similarity"], dict(r))
                    for r in semantic_rows
                    if r["similarity"] >= float(os.getenv("SEMANTIC_MIN_SCORE", ".30"))
                ]
                seen = {r["id"] for r in rows}
                rows += [row for _, row in semantic if row["id"] not in seen]
            return retrieve(rows, query, semantic=semantic)
        rows = c.execute(select + permitted, (user["org"], user["id"])).fetchall()
    return retrieve(rows, query)


@router.get("/api/v1/conversations")
def conversations(user=Depends(current_user)):
    with db() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM conversations WHERE org=? AND user_id=? ORDER BY created DESC",
                (user["org"], user["id"]),
            )
        ]


@router.post("/api/v1/conversations", status_code=201)
def create_conversation(user=Depends(current_user)):
    conversation_id = uid()
    with db() as c:
        if demo_enabled() and c.execute("SELECT COUNT(*) AS n FROM conversations WHERE user_id=?", (user["id"],)).fetchone()["n"] >= 30:
            raise HTTPException(429, "This workspace allows 30 conversations. Delete an old conversation to continue.")
        c.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?)",
            (conversation_id, user["org"], user["id"], "New conversation", now()),
        )
    return {"id": conversation_id}


def check_conversation(c, conversation_id, user):
    if not c.execute(
        "SELECT id FROM conversations WHERE id=? AND org=? AND user_id=?",
        (conversation_id, user["org"], user["id"]),
    ).fetchone():
        raise HTTPException(404, "Conversation not found.")


@router.get("/api/v1/conversations/{conversation_id}/messages")
def messages(conversation_id: str, user=Depends(current_user)):
    with db() as c:
        check_conversation(c, conversation_id, user)
        visible = {
            row["id"] for row in c.execute(
                "SELECT id FROM documents WHERE org=? AND (visibility='workspace' OR owner=?)",
                (user["org"], user["id"]),
            )
        }
        result = []
        for r in c.execute(
            "SELECT * FROM messages WHERE conversation=? ORDER BY created",
            (conversation_id,),
        ):
            message = dict(r)
            sources = []
            for index, source in enumerate(json.loads(message["citations"]), 1):
                source.setdefault("citation_number", index)
                if source.get("document") in visible:
                    sources.append(source)
            message["citations"] = sources
            result.append(message)
        return result


def generate_reply(conversation_id, body, user):
    query = body.content.strip()
    if not query:
        raise HTTPException(422, "Enter a question.")
    started = time.monotonic()
    run_token = uid()
    with db() as c:
        check_conversation(c, conversation_id, user)
        if demo_enabled() and c.execute("SELECT COUNT(*) AS n FROM messages m JOIN conversations c ON c.id=m.conversation WHERE c.user_id=?", (user["id"],)).fetchone()["n"] >= 300:
            raise HTTPException(429, "Message limit reached. Delete an old conversation to continue.")
        c.execute("DELETE FROM chat_runs WHERE expires<?", (time.time(),))
        try:
            c.execute(
                "INSERT INTO chat_runs VALUES (?,?,?)",
                (conversation_id, run_token, time.time() + 180),
            )
        except IntegrityError:
            raise HTTPException(
                409, "An answer is already being generated in this conversation."
            ) from None
        history = [
            dict(r)
            for r in c.execute(
                "SELECT role,content FROM messages WHERE conversation=? ORDER BY created DESC LIMIT 6",
                (conversation_id,),
            )
        ][::-1]
    try:
        retrieval_query = query
        import re

        if (
            len(query.split()) < 16
            and history
            and re.search(
                r"\b(it|its|they|their|them|that|those|this|these|more|same|above)\b",
                query,
                re.I,
            )
        ):
            retrieval_query += (
                " "
                + next(
                    (h["content"] for h in reversed(history) if h["role"] == "user"), ""
                )[-1500:]
            )
        page_images = []
        if body.visual_document_id:
            if not body.visual_page:
                raise HTTPException(422, "Choose a page for visual analysis.")
            if not generation_provider():
                raise HTTPException(
                    422, "Visual analysis needs a configured Gemini or OpenAI model."
                )
            import base64

            from app.extraction import ExtractionError
            from app.processing import page_image

            with db() as c:
                doc = permitted_document(c, body.visual_document_id, user)
                version = c.execute(
                    "SELECT * FROM document_versions WHERE document=? AND number=?",
                    (doc["id"], doc["version"]),
                ).fetchone()
                if not version or version["status"] != "ready":
                    raise HTTPException(
                        409, "Wait for this document to finish indexing."
                    )
                if (version["original"] is None and not version["original_key"]) or not visual_file(version["filename"]):
                    raise HTTPException(
                        422, "Visual analysis requires an original PDF or image."
                    )
                pages = json.loads(version["pages"])
                if body.visual_page > len(pages):
                    raise HTTPException(422, "Page number is outside this PDF.")
                source = {
                    "document": doc["id"],
                    "title": doc["title"],
                    "version_id": version["id"],
                    "version": version["number"],
                    "page": body.visual_page,
                    "content": pages[body.visual_page - 1]
                    or "Visual source page; consult the attached image.",
                }
                original_source = dict(version)
            original_data = stored_original(original_source)
            try:
                image = page_image(original_data, body.visual_page)
            except ExtractionError as error:
                raise HTTPException(422, str(error)) from None
            page_images = [
                "data:image/png;base64," + base64.b64encode(image).decode("ascii")
            ]
            sources = [source]
        else:
            sources = search(Question(content=retrieval_query[:3000]), user)
        sources = [
            dict(source, citation_number=i) for i, source in enumerate(sources, 1)
        ]
        consume_demo_question(user)
        yield {"type": "citations", "citations": sources}
        text, mode, total = "", "extractive", 0
        try:
            events = (
                stream_answer(query, sources, history, page_images)
                if page_images
                else stream_answer(query, sources, history)
            )
            for event in events:
                if event["type"] == "delta":
                    text += event["text"]
                    yield event
                elif event["type"] == "usage":
                    mode, total = event["model"], event["tokens"]
        except HTTPException as error:
            if error.status_code != 503 or text or not sources:
                raise
            # Outages must never be misreported as missing evidence. This is
            # an explicit excerpt response, not another provider or a fake LLM.
            text = (
                "AI synthesis is temporarily unavailable. Your document was found.\n"
                "The following are source excerpts, not an AI-generated answer.\n\n"
                + (
                    "The selected page image could not be interpreted. Diagram relationships are not verified.\n\n"
                    if page_images
                    else ""
                )
                + "\n\n".join(
                    f"[{i}] {source['content']}"
                    for i, source in enumerate(sources[:2], 1)
                )
            )
            mode, total = "extractive", 0
            yield {"type": "delta", "text": text}
        if not text:
            raise HTTPException(
                502, "The answer provider returned no content. Please retry."
            )
        # Reject invented citation indices before saving a completed answer.
        import re

        bad = [
            int(n)
            for n in re.findall(r"\[(\d+)\]", text)
            if not 1 <= int(n) <= len(sources)
        ]
        if mode != "extractive" and bad:
            raise HTTPException(
                502, "The model returned invalid source references. Please retry."
            )
        message_id = uid()
        with db() as c:
            check_conversation(c, conversation_id, user)
            if not c.execute(
                "SELECT token FROM chat_runs WHERE conversation=? AND token=? AND expires>?",
                (conversation_id, run_token, time.time()),
            ).fetchone():
                raise HTTPException(409, "This answer expired. Please retry.")
            c.execute(
                "INSERT INTO messages (id,conversation,role,content,created) VALUES (?,?,?,?,?)",
                (uid(), conversation_id, "user", query, now()),
            )
            c.execute(
                "INSERT INTO messages (id,conversation,role,content,citations,created,latency,model,tokens) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    message_id,
                    conversation_id,
                    "assistant",
                    text,
                    json.dumps(sources),
                    now(),
                    int((time.monotonic() - started) * 1000),
                    mode,
                    total,
                ),
            )
            c.execute(
                "UPDATE conversations SET title=? WHERE id=? AND title='New conversation'",
                (query[:70], conversation_id),
            )
            audit(c, user, "chat.answered", conversation_id)
        yield {
            "type": "done",
            "id": message_id,
            "content": text,
            "citations": sources,
            "mode": mode,
            "tokens": total,
        }
    finally:
        with db() as c:
            c.execute(
                "DELETE FROM chat_runs WHERE conversation=? AND token=?",
                (conversation_id, run_token),
            )


@router.post("/api/v1/conversations/{conversation_id}/messages")
def ask(conversation_id: str, body: Question, user=Depends(current_user)):
    result = None
    for event in generate_reply(conversation_id, body, user):
        if event["type"] == "done":
            result = {k: v for k, v in event.items() if k != "type"}
    return result


@router.post("/api/v1/conversations/{conversation_id}/stream")
async def stream_reply(
    conversation_id: str, body: Question, request: Request, user=Depends(current_user)
):
    with db() as c:
        check_conversation(c, conversation_id, user)
    if not body.content.strip():
        raise HTTPException(422, "Enter a question.")
    iterator = generate_reply(conversation_id, body, user)

    async def events():
        try:
            while not await request.is_disconnected():
                item = await run_in_threadpool(lambda: next(iterator, None))
                if item is None:
                    break
                yield "data: " + json.dumps(item) + "\n\n"
        except HTTPException as error:
            yield (
                "data: "
                + json.dumps({"type": "error", "message": error.detail})
                + "\n\n"
            )
        except Exception:
            logging.getLogger("knowra").exception("Answer stream failed")
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "error",
                        "message": "The answer was interrupted. Please retry.",
                    }
                )
                + "\n\n"
            )
        finally:
            # Shield cleanup so cancellation releases the per-conversation lease.
            import anyio

            with anyio.CancelScope(shield=True):
                await run_in_threadpool(iterator.close)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.delete("/api/v1/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user=Depends(current_user)):
    with db() as c:
        check_conversation(c, conversation_id, user)
        c.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
    return {"ok": True}


class Feedback(BaseModel):
    value: int = Field(ge=-1, le=1)


@router.post("/api/v1/messages/{message_id}/feedback")
def feedback(message_id: str, body: Feedback, user=Depends(current_user)):
    with db() as c:
        row = c.execute(
            "SELECT conversation FROM messages WHERE id=? AND role=?",
            (message_id, "assistant"),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Message not found.")
        check_conversation(c, row["conversation"], user)
        c.execute("UPDATE messages SET feedback=? WHERE id=?", (body.value, message_id))
    return {"ok": True}

