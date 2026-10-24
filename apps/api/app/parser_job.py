"""Disposable parser child; its supervisor/container enforce time and memory limits."""

import base64
import json
import sys
from pathlib import Path


def execute(payload):
    data = base64.b64decode(payload["data"], validate=True)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("File too large")
    operation = payload["operation"]
    from app.extraction import IMAGE_EXTENSIONS, extract_image, extract_pdf, page_image
    from app.rag import parse_file

    if operation == "validate":
        return {"pages": parse_file(payload["filename"], data)}
    if operation == "extract":
        filename = payload["filename"].lower()
        if filename.endswith(".pdf"):
            pages, layout = extract_pdf(data, payload.get("pages"))
        elif filename.endswith(IMAGE_EXTENSIONS):
            pages, layout = extract_image(data)
        else:
            raise ValueError("Unsupported visual source")
        return {"pages": pages, "layout": layout}
    number = payload.get("number")
    if type(number) is not int or not 1 <= number <= 300:
        raise ValueError("Invalid page")
    if operation == "image":
        return {"image": base64.b64encode(page_image(data, number)).decode()}
    if operation == "highlight":
        from app.evidence import highlight

        pages, quote = payload["pages"], payload["quote"]
        if not 1 <= number <= len(pages) or len(pages[number - 1]) > 100_000 or len(quote) > 4000:
            raise ValueError("Evidence bounds exceeded")
        return highlight(pages, number, quote, data)
    raise ValueError("Unknown operation")


if __name__ == "__main__":
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    request = sys.stdin.buffer.read(18 * 1024 * 1024 + 1)
    if len(request) > 18 * 1024 * 1024:
        raise ValueError("Request too large")
    Path(sys.argv[1]).write_text(json.dumps(execute(json.loads(request))), encoding="utf-8")
