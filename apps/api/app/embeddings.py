"""Local embeddings. Explicit model configuration prevents silent external downloads."""

import json
import logging
import math
import os
from functools import lru_cache
from threading import Lock

_inference_lock = Lock()


def warmup():
    """Load cached model weights in the background instead of on a user's question."""
    if model_name():
        try:
            encode(["Knowledge search warmup"])
        except Exception:
            logging.getLogger("knowra.embeddings").exception(
                "Semantic search warmup failed"
            )


def model_name():
    return os.getenv("EMBEDDING_MODEL", "").strip()


@lru_cache(maxsize=2)
def model(name):
    import torch

    torch.set_num_threads(int(os.getenv("EMBEDDING_THREADS", "2")))
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        name,
        local_files_only=os.getenv("EMBEDDING_ALLOW_DOWNLOAD") != "true",
        device="cpu",
    )


def encode(texts):
    name = model_name()
    if not name:
        return [None] * len(texts)
    vectors = []
    for start in range(0, len(texts), 32):
        # Release between batches so one large upload does not monopolize
        # the inference lock for its entire document.
        with _inference_lock:
            vectors.extend(
                model(name).encode(
                    texts[start:start + 32], normalize_embeddings=True,
                    show_progress_bar=False, batch_size=32,
                ).tolist()
            )
    return vectors


@lru_cache(maxsize=128)
def _query_vector(name, query):
    # Cache vectors only, never source sets or authorization decisions.
    # Include the model in the key; return immutable data to callers.
    with _inference_lock:
        return tuple(
            model(name).encode(
                [query], normalize_embeddings=True, show_progress_bar=False,
                batch_size=1,
            ).tolist()[0]
        )


def query_vector(query):
    name = model_name()
    return list(_query_vector(name, query)) if name else None


def cosine(a, b):
    if len(a) != len(b):
        return -1
    denominator = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return (
        sum(x * y for x, y in zip(a, b, strict=True)) / denominator
        if denominator
        else 0
    )


def semantic_rank(rows, query):
    name = model_name()
    candidates = [
        r for r in rows if r.get("embedding") and r.get("embedding_model") == name
    ]
    if not name or not candidates:
        return []
    vector = query_vector(query)
    scores = [(cosine(vector, json.loads(r["embedding"])), r) for r in candidates]
    threshold = float(os.getenv("SEMANTIC_MIN_SCORE", ".30"))
    return [
        (score, r)
        for score, r in sorted(scores, key=lambda p: p[0], reverse=True)
        if score >= threshold
    ][:30]
