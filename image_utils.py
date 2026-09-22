"""Shared helper for turning uploaded images/PDFs into base64 data URLs for vision requests."""

import base64
import io

import pillow_heif
import pymupdf as fitz
from PIL import Image

pillow_heif.register_heif_opener()

HEIC_EXTS = {".heic", ".heif"}
PASSTHROUGH_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Cap on the longest edge of any image we send to the vision API, in pixels.
# 200 DPI on a normal A4/letter page comes out well under this, so ordinary
# scans are unaffected - but some phone "scan to PDF" apps declare a page size
# equal to the photo's pixel dimensions (interpreted as points, i.e. 1/72
# inch), which made a single page rasterize at 200 DPI to many thousands of
# pixels per side and blew well past the server's memory limit. This clamps
# the render resolution regardless of what the file claims its page size is.
MAX_DIM = 2500
TARGET_DPI = 200


def _scaled_pdf_pixmap(page):
    zoom = TARGET_DPI / 72
    longest_pt = max(page.rect.width, page.rect.height)
    if longest_pt * zoom > MAX_DIM:
        zoom = MAX_DIM / longest_pt
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))


def _load_capped(file_path, ext):
    """Decode a raster image capped to MAX_DIM on its longest edge, without
    ever fully decoding a much larger original into memory first. A modern
    phone's 48MP JPEG can be a ~3MB file that decodes to 8000x6000px - over
    140MB uncompressed - even though we only need ~2500px of it, and doing
    that for several photos in one request was enough to blow past the
    server's memory limit. For JPEGs, draft() asks libjpeg to decode at a
    reduced DCT scale (1/2, 1/4, 1/8) directly, so the oversized decode never
    happens in the first place; for other formats we at least skip it when
    the file's header says it's already small enough.
    """
    img = Image.open(file_path)
    if ext in (".jpg", ".jpeg"):
        img.draft("RGB", (MAX_DIM, MAX_DIM))
    img.load()
    img = img.convert("RGB")
    if max(img.size) > MAX_DIM:
        img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)
    return img


def file_to_image_data_urls(file_path):
    """Convert an uploaded image or PDF into a list of base64 data URLs (one per page/image)."""
    ext = file_path.suffix.lower()
    urls = []
    if ext == ".pdf":
        doc = fitz.open(file_path)
        try:
            for page in doc:
                pix = _scaled_pdf_pixmap(page)
                png_bytes = pix.tobytes("png")
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                urls.append(f"data:image/png;base64,{b64}")
        finally:
            doc.close()
    else:
        # A cheap header read (no pixel decode) tells us the real dimensions,
        # so a normal-sized phone/scan photo can skip decoding entirely and
        # go straight through as the original bytes.
        probe = Image.open(file_path)
        native_size = probe.size
        probe.close()

        if ext in PASSTHROUGH_EXTS and max(native_size) <= MAX_DIM:
            media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            urls.append(f"data:{media_type};base64,{b64}")
        else:
            img = _load_capped(file_path, ext)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            urls.append(f"data:image/jpeg;base64,{b64}")
    return urls
