"""Local, bounded PDF OCR and layout extraction. Originals remain immutable."""

import io
import math
import os
import threading
import time

import pymupdf

# MuPDF and the shared OCR engine must not be used concurrently by worker/API threads.
PDF_LOCK = threading.RLock()
OCR_LOCK = threading.Lock()
_ocr = None
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def visual_file(name):
    return name.lower().endswith((".pdf", *IMAGE_EXTENSIONS))


def load_image(data):
    """Validate decoded type and size before allocating a full raster."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"}:
                raise ExtractionError("Use a PNG, JPEG or WebP image.")
            if image.width * image.height > 20_000_000 or max(image.size) > 12000:
                raise ExtractionError(
                    "Images are limited to 20 megapixels and 12,000 pixels per side."
                )
            if getattr(image, "n_frames", 1) != 1:
                raise ExtractionError("Upload a still image rather than an animation.")
            image.load()
            result = ImageOps.exif_transpose(image).convert("RGBA")
            background = Image.new("RGBA", result.size, "white")
            background.alpha_composite(result)
            result = background.convert("RGB")
            scale = min(1, math.sqrt(4_000_000 / (result.width * result.height)))
            if scale < 1:
                result = result.resize(
                    (
                        max(1, int(result.width * scale)),
                        max(1, int(result.height * scale)),
                    )
                )
            return result
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        if isinstance(error, ExtractionError):
            raise
        raise ExtractionError(
            "Cannot read this image. Upload a valid PNG, JPEG or WebP file."
        ) from None


def extract_image(data):
    image = load_image(data)
    with OCR_LOCK:
        result = ocr_engine()(image)
    items = (
        [
            (b, t, s)
            for b, t, s in zip(result.boxes, result.txts, result.scores, strict=True)
            if s >= 0.5
        ]
        if result.txts
        else []
    )
    text = "\n".join(t for _, t, _ in items)
    tables = scanned_tables(image, items)
    text += (
        "\n\n" + "\n\n".join(table_text(rows, n) for n, rows in enumerate(tables, 1))
        if tables
        else ""
    )
    warnings = [
        "OCR may misread small text, numbers or handwriting. Check the original image.",
        "Use visual analysis for arrows, charts and visual relationships.",
    ]
    if not text.strip():
        warnings.append(
            "No readable text was detected. Select this image in visual analysis to ask about its contents."
        )
    if len(text) > 2_000_000:
        raise ExtractionError("Extracted text exceeds the 2 million character limit.")
    return [text], [{"method": "ocr", "tables": tables, "warnings": warnings}]


class ExtractionError(ValueError):
    pass


def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr import RapidOCR

        _ocr = RapidOCR(
            params={
                "Global.log_level": "error",
                "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )
    return _ocr


def pixmap(page, dpi=180, clip=None):
    rect = clip if clip is not None else page.rect
    area = max(1, rect.width * rect.height)
    scale = min(dpi / 72, math.sqrt(4_000_000 / area))
    return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False, clip=clip)


def page_image(data, number):
    if not data.startswith(b"%PDF-"):
        if number != 1:
            raise ExtractionError("Images have one page. Choose page 1.")
        buffer = io.BytesIO()
        load_image(data).save(buffer, format="PNG")
        return buffer.getvalue()
    with PDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as pdf:
        if not 1 <= number <= len(pdf):
            raise ExtractionError("Page number is outside this PDF.")
        return pixmap(pdf[number - 1], 140).tobytes("png")


def table_text(rows, number):
    """Repeat column labels on every row so chunks retain cell relationships."""
    rows = [
        [str(cell or "").replace("\n", " ").strip() for cell in row] for row in rows
    ]
    if len(rows) < 2 or len(rows[0]) < 2:
        return ""
    headers = [cell or f"Column {i + 1}" for i, cell in enumerate(rows[0])]
    return "\n".join(
        f"Table {number}: "
        + "; ".join(
            f"{headers[i] if i < len(headers) else f'Column {i + 1}'}: {cell}"
            for i, cell in enumerate(row)
        )
        for row in rows[1:]
        if any(row)
    )


def scanned_tables(image, items):
    """Recover ruled scan tables from grid lines, assigning OCR boxes to cells."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    ink = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((1, max(40, gray.shape[1] // 15)), np.uint8)
    )
    vertical = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, np.ones((max(40, gray.shape[0] // 15), 1), np.uint8)
    )
    contours, _ = cv2.findContours(
        horizontal | vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    tables = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < 100 or h < 50:
            continue

        def positions(values, threshold):
            indices = np.flatnonzero(values > threshold)
            groups = []
            for value in indices:
                if not groups or value - groups[-1][-1] > 3:
                    groups.append([])
                groups[-1].append(int(value))
            return [sum(group) / len(group) for group in groups]

        xs = positions((vertical[y : y + h, x : x + w] > 0).sum(axis=0), h * 0.6)
        ys = positions((horizontal[y : y + h, x : x + w] > 0).sum(axis=1), w * 0.6)
        if not (3 <= len(xs) <= 30 and 3 <= len(ys) <= 150):
            continue
        rows = [[[] for _ in range(len(xs) - 1)] for _ in range(len(ys) - 1)]
        for box, text, _score in items:
            cx = sum(p[0] for p in box) / 4 - x
            cy = sum(p[1] for p in box) / 4 - y
            col = next(
                (i for i in range(len(xs) - 1) if xs[i] <= cx <= xs[i + 1]), None
            )
            row = next(
                (i for i in range(len(ys) - 1) if ys[i] <= cy <= ys[i + 1]), None
            )
            if col is not None and row is not None:
                rows[row][col].append(text)
        clean = [[" ".join(cell) for cell in row] for row in rows]
        if sum(bool(cell) for row in clean for cell in row) >= 4:
            tables.append(clean)
    return tables[:20]


def extract_pdf(data, fallback_pages=None):
    from PIL import Image

    pages, layout = [], []
    fallback_reader = None
    started, ocr_count = time.monotonic(), 0
    limit = min(300, max(1, int(os.getenv("OCR_MAX_PAGES", "50"))))
    with PDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as pdf:
        if pdf.needs_pass or len(pdf) > 300:
            raise ExtractionError("Use an unencrypted PDF with at most 300 pages.")
        for page in pdf:
            if time.monotonic() - started > 240:
                raise ExtractionError(
                    "Document processing exceeded four minutes. Split this PDF into smaller files."
                )
            text = page.get_text(sort=True).strip()
            if not text and fallback_pages and page.number < len(fallback_pages):
                text = fallback_pages[page.number].strip()
            meta = {"method": "text", "tables": [], "warnings": []}
            if not text:
                # Some imperfect PDFs are readable by a second text engine
                # even when MuPDF cannot render their content streams.
                # Load it lazily in the worker, never during upload.
                try:
                    from pypdf import PdfReader

                    if fallback_reader is None:
                        fallback_reader = PdfReader(io.BytesIO(data))
                    text = fallback_reader.pages[page.number].extract_text() or ""
                    if text.strip():
                        meta["warnings"].append(
                            "Text recovered with a secondary PDF reader. Verify it against the original."
                        )
                except Exception:
                    # OCR can still recover an image-only page.
                    pass
            native_text = text
            meta["tables"] = [
                t.extract()
                for t in page.find_tables().tables
                if t.row_count >= 2 and t.col_count >= 2
            ][:20]
            # Include OCR for mixed pages as well as scans, but skip tiny decorative images.
            images = page.get_image_info()
            image_rects = [
                pymupdf.Rect(i["bbox"])
                for i in images
                if pymupdf.Rect(i["bbox"]).get_area() > page.rect.get_area() * 0.08
            ]
            large_image = bool(image_rects)
            if len(text) < 5 or large_image:
                ocr_count += 1
                if ocr_count > limit:
                    raise ExtractionError(
                        f"This PDF needs OCR on more than {limit} pages. Split it into smaller files."
                    )
                # On mixed pages, OCR only the image area; native paragraphs are
                # already available and recognizing them again is costly.
                clip = None
                if len(native_text) >= 50 and image_rects:
                    clip = pymupdf.Rect(image_rects[0])
                    for rect in image_rects[1:]:
                        clip |= rect
                    clip = (clip * page.rotation_matrix) & page.rect
                image = Image.open(
                    io.BytesIO(pixmap(page, clip=clip).tobytes("png"))
                ).convert("RGB")
                with OCR_LOCK:
                    result = ocr_engine()(image)
                items = (
                    list(zip(result.boxes, result.txts, result.scores, strict=True))
                    if result.txts
                    else []
                )
                readable = [(b, t, s) for b, t, s in items if s >= 0.5]
                ocr_text = "\n".join(t for _, t, _ in readable)
                # Preserve selectable text even if OCR misses a native paragraph.
                missing = [
                    line
                    for line in native_text.splitlines()
                    if line.strip() and line.casefold() not in ocr_text.casefold()
                ]
                text = ocr_text + ("\n" + "\n".join(missing) if missing else "")
                meta["method"] = (
                    "ocr" if len(page.get_text().strip()) < 50 else "text + OCR"
                )
                for table in scanned_tables(image, readable):
                    if table not in meta["tables"]:
                        meta["tables"].append(table)
                meta["warnings"].append(
                    "OCR may misread small text, numbers or handwriting. Check the original page."
                )
            if images or page.get_drawings():
                meta["warnings"].append(
                    "Diagram labels are searchable. Arrows, charts and visual relationships require visual analysis."
                )
            table_passages = [
                table_text(rows, n) for n, rows in enumerate(meta["tables"], 1)
            ]
            text = text + (
                "\n\n" + "\n\n".join(table_passages) if table_passages else ""
            )
            pages.append(text)
            layout.append(meta)
            if sum(map(len, pages)) > 2_000_000:
                raise ExtractionError(
                    "Extracted text exceeds the 2 million character limit."
                )
    if not any(p.strip() for p in pages):
        raise ExtractionError(
            "No readable text found after OCR. Upload a clearer scan or a document containing text."
        )
    return pages, layout
