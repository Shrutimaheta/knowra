"""Locate a supplied passage and highlight real text/boxes without an LLM."""

import base64
import io
import os
import re
from difflib import SequenceMatcher

import pymupdf
from app.extraction import OCR_LOCK, PDF_LOCK, ocr_engine, page_image
from PIL import Image, ImageDraw


def words(text):
    return list(re.finditer(r"\w+", text))


def locate(text, quote):
    original, query = words(text), words(quote)
    if not original or not query:
        return []
    matcher = SequenceMatcher(
        None,
        [m.group().casefold() for m in query],
        [m.group().casefold() for m in original],
        autojunk=False,
    )
    match = matcher.find_longest_match()
    # Never mark a few common words as proof for a longer passage.
    if match.size < min(6, len(query)) or match.size < len(query) * 0.5:
        return []
    return [
        {
            "start": original[match.b].start(),
            "end": original[match.b + match.size - 1].end(),
            "exact": match.size == len(query),
        }
    ]


def boxes_for(entries, quote):
    tokens, owner = [], []
    for text, box in entries:
        for match in words(text):
            tokens.append(match.group().casefold())
            owner.append(box)
    query = [m.group().casefold() for m in words(quote)]
    if not tokens or not query:
        return []
    matcher = SequenceMatcher(None, query, tokens, autojunk=False)
    boxes = []
    for block in matcher.get_matching_blocks():
        if block.size >= min(4, len(query)):
            boxes.extend(owner[block.b : block.b + block.size])
    return boxes


def highlight(pages, number, quote, data=None):
    text = pages[number - 1]
    ranges = locate(text, quote)
    result = {
        "page": number,
        "ranges": ranges,
        "image": None,
        "boxes": [],
        "notice": "No matching passage was located on this page. Open the original to verify the source.",
    }
    if not ranges:
        return result
    span = ranges[0]
    matched = text[span["start"] : span["end"]]
    result["notice"] = (
        "Supporting passage highlighted. This locates source text; it does not independently verify the answer."
    )
    if not span["exact"]:
        result["notice"] = (
            "A matching portion of the passage is highlighted. Some supplied text could not be located on this page."
        )
    if data is None:
        return result
    image = Image.open(io.BytesIO(page_image(data, number))).convert("RGB")
    entries = []
    if data.startswith(b"%PDF-"):
        with PDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as pdf:
            page = pdf[number - 1]
            for x0, y0, x1, y1, value, *_ in page.get_text("words", sort=True):
                rect = pymupdf.Rect(x0, y0, x1, y1) * page.rotation_matrix
                entries.append(
                    (
                        value,
                        (
                            rect.x0 / page.rect.width,
                            rect.y0 / page.rect.height,
                            rect.x1 / page.rect.width,
                            rect.y1 / page.rect.height,
                        ),
                    )
                )
    boxes = boxes_for(entries, matched)
    if not boxes and os.getenv("APP_ENV") == "demo":
        result["notice"] += " Extracted text is highlighted; live image OCR is disabled in this lightweight demo."
        return result
    if not boxes:
        # Older OCR versions have no saved geometry. Read only this source page
        # locally; its OCR text is matched again before any region is highlighted.
        with OCR_LOCK:
            output = ocr_engine()(image)
        entries = []
        if output.txts:
            for points, value, score in zip(
                output.boxes, output.txts, output.scores, strict=True
            ):
                if score >= 0.5:
                    xs, ys = [p[0] for p in points], [p[1] for p in points]
                    entries.append(
                        (
                            value,
                            (
                                min(xs) / image.width,
                                min(ys) / image.height,
                                max(xs) / image.width,
                                max(ys) / image.height,
                            ),
                        )
                    )
        boxes = boxes_for(entries, matched)
    if not boxes:
        result["notice"] += (
            " Original-page highlighting was unavailable; the extracted text is highlighted below."
        )
        return result
    boxes = list(dict.fromkeys(tuple(float(v) for v in box) for box in boxes))[:1000]
    overlay = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in boxes:
        draw.rectangle(
            (x0 * image.width, y0 * image.height, x1 * image.width, y1 * image.height),
            fill=(255, 206, 40, 100),
        )
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result.update(
        image="data:image/png;base64,"
        + base64.b64encode(buffer.getvalue()).decode("ascii"),
        boxes=boxes,
    )
    return result
