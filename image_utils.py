"""Shared helper for turning uploaded images/PDFs into base64 data URLs for vision requests."""

import base64

import pymupdf as fitz

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
        # Real photo dimensions can't lie about content size the way a PDF's
        # declared page size can, so this is a cheap safety net rather than
        # the main fix - only re-encode (as PNG) if actually oversized, to
        # avoid needlessly inflating an ordinary JPEG photo.
        pix = fitz.Pixmap(str(file_path))
        if max(pix.width, pix.height) > MAX_DIM:
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            scale = MAX_DIM / max(pix.width, pix.height)
            pix = fitz.Pixmap(pix, pix.width * scale, pix.height * scale)
            b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
            urls.append(f"data:image/png;base64,{b64}")
        else:
            media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            with open(file_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            urls.append(f"data:{media_type};base64,{b64}")
    return urls
