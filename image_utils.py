"""Shared helper for turning uploaded images/PDFs into base64 data URLs for vision requests."""

import base64

import pymupdf as fitz


def file_to_image_data_urls(file_path):
    """Convert an uploaded image or PDF into a list of base64 data URLs (one per page/image)."""
    ext = file_path.suffix.lower()
    urls = []
    if ext == ".pdf":
        doc = fitz.open(file_path)
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                png_bytes = pix.tobytes("png")
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                urls.append(f"data:image/png;base64,{b64}")
        finally:
            doc.close()
    else:
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        urls.append(f"data:{media_type};base64,{b64}")
    return urls
