from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageStat
from PyPDF2 import PdfReader

log = logging.getLogger("media")


@dataclass(frozen=True)
class ImageInfo:
    ok: bool
    description: str


def describe_image(image_bytes: bytes) -> ImageInfo:
    if not image_bytes:
        return ImageInfo(ok=False, description="No image bytes found.")
    try:
        im = Image.open(io.BytesIO(image_bytes))
        im = im.convert("RGB")
        w, h = im.size
        orientation = "landscape" if w > h else "portrait" if h > w else "square"
        stat = ImageStat.Stat(im)
        r, g, b = [int(x) for x in stat.mean]
        desc = (
            f"Image received: {w}x{h} ({orientation}), RGB average color approx ({r},{g},{b}). "
            f"No vision model used; this is metadata-level description."
        )
        return ImageInfo(ok=True, description=desc)
    except Exception as e:
        log.exception("describe_image failed")
        return ImageInfo(ok=False, description=f"Could not parse image: {e}")


@dataclass(frozen=True)
class PDFText:
    ok: bool
    text: str
    error: Optional[str]


def extract_pdf_text(pdf_bytes: bytes, max_chars: int = 12000) -> PDFText:
    if not pdf_bytes:
        return PDFText(ok=False, text="", error="empty_pdf")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = []
        for page in reader.pages[:20]:  # cap pages
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            if t:
                parts.append(t)
            if sum(len(x) for x in parts) > max_chars:
                break
        text = "\n\n".join(parts).strip()
        if len(text) > max_chars:
            text = text[:max_chars]
        return PDFText(ok=True, text=text, error=None)
    except Exception as e:
        log.exception("extract_pdf_text failed")
        return PDFText(ok=False, text="", error=str(e))
