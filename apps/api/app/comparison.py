"""Bounded, deterministic comparisons with immutable page references."""

import re
from difflib import SequenceMatcher

from fastapi import HTTPException


def units(pages):
    result = []
    for page, text in enumerate(pages, 1):
        # Ignore a single line wrap inside a sentence, preserving source offsets.
        for match in re.finditer(r"\S[\s\S]*?(?:[.!?](?=\s|$)|\n[ \t]*\n|$)", text):
            value = match.group().strip()
            if value:
                start = match.start()
                result.append(
                    {
                        "page": page,
                        "start": start,
                        "end": start + len(value),
                        "text": value,
                    }
                )
    return result


def segments(text, other):
    tokens = list(re.finditer(r"\w+|[^\w\s]", text))
    peers = re.findall(r"\w+|[^\w\s]", other)
    if len(tokens) > 2000 or len(peers) > 2000:
        return [{"text": text, "changed": True}]
    changed = set()
    for tag, start, end, _, _ in SequenceMatcher(
        None, [m.group() for m in tokens], peers, autojunk=False
    ).get_opcodes():
        if tag != "equal":
            changed.update(range(start, end))
    result, position = [], 0
    for i, _match in enumerate(tokens):
        end = tokens[i + 1].start() if i + 1 < len(tokens) else len(text)
        value = text[position:end]
        flag = i in changed
        if result and result[-1]["changed"] == flag:
            result[-1]["text"] += value
        else:
            result.append({"text": value, "changed": flag})
        position = end
    return result or [{"text": text, "changed": False}]


def compare_pages(before, after):
    if sum(map(len, before)) + sum(map(len, after)) > 400_000:
        raise HTTPException(
            413,
            "Compare files with at most 400,000 combined extracted characters. Split larger documents first.",
        )
    left, right = units(before), units(after)
    if len(left) + len(right) > 4000:
        raise HTTPException(
            413,
            "Too many passages to compare at once. Split the documents into smaller sections.",
        )

    def keys(rows):
        return [" ".join(r["text"].split()) for r in rows]

    changes, counts = [], {"added": 0, "removed": 0, "modified": 0}
    for tag, a, b, c, d in SequenceMatcher(
        None, keys(left), keys(right), autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        old, new = left[a:b], right[c:d]
        for index in range(max(len(old), len(new))):
            first = dict(old[index]) if index < len(old) else None
            second = dict(new[index]) if index < len(new) else None
            kind = "modified" if first and second else "removed" if first else "added"
            counts[kind] += 1
            if len(changes) >= 200:
                continue
            for item, peer in ((first, second), (second, first)):
                if item:
                    item["segments"] = segments(
                        item["text"], peer["text"] if peer else ""
                    )
            changes.append({"kind": kind, "before": first, "after": second})
    return {
        "changes": changes,
        "counts": counts,
        "total": sum(counts.values()),
        "truncated": sum(counts.values()) > len(changes),
        "method": "extracted-text",
        "notice": "Changes are based on extracted text. Review original pages, especially for OCR. Moved or reformatted passages may appear as changes.",
    }
