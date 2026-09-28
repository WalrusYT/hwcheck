"""Shared helper for turning uploaded images/PDFs into base64 data URLs for vision requests."""

import base64
import io

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()


def _fitz():
    # PyMuPDF costs ~25 MB, and gunicorn's master imports the app too: load it on
    # first use in the worker instead of in every process at startup (512 MB box).
    import pymupdf

    return pymupdf

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
    return page.get_pixmap(matrix=_fitz().Matrix(zoom, zoom))


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


def load_pages(file_path):
    """Yield decoded RGB page images (one per PDF page, one for a photo), capped at
    MAX_DIM - one at a time, so a many-page upload never sits in memory all at once."""
    if file_path.suffix.lower() == ".pdf":
        fitz = _fitz()
        doc = fitz.open(file_path)
        try:
            for page in doc:
                pix = _scaled_pdf_pixmap(page)
                if pix.alpha or pix.n != 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix, 0)
                yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        finally:
            doc.close()
    else:
        yield _load_capped(file_path, file_path.suffix.lower())


def image_to_data_url(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def fit_like_openai_high_detail(img):
    """Resize the way OpenAI's gpt-4o preprocesses a "high" detail image: fit within
    2048x2048, then shrink so the short side is at most 768 px. The model sees the
    same pixels; the request is several times smaller, which matters on a 512 MB
    server holding a multi-photo submission in memory while the request is sent."""
    fit_box = min(1.0, 2048 / max(img.size))
    short_side = min(1.0, 768 / (min(img.size) * fit_box))
    scale = fit_box * short_side
    if scale >= 1.0:
        return img
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def horizontal_strips(img, count=3, overlap=0.12):
    """Overlapping full-width bands of a page. The vision API downscales a whole
    page to roughly 768px on its short side, where dense handwritten fractions
    become unreadable; each band is sent at close to native resolution instead."""
    band = img.height / count
    pad = int(band * overlap)
    strips = []
    for i in range(count):
        top = max(0, int(i * band) - pad)
        bottom = min(img.height, int((i + 1) * band) + pad)
        strips.append(img.crop((0, top, img.width, bottom)))
    return strips


def file_to_image_data_urls(file_path):
    """Convert an uploaded image or PDF into a list of base64 data URLs (one per page/image)."""
    ext = file_path.suffix.lower()
    urls = []
    if ext == ".pdf":
        doc = _fitz().open(file_path)
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
