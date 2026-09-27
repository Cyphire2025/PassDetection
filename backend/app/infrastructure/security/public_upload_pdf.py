"""Single-page public PDF rasterization in a short-lived, bounded process."""

from __future__ import annotations

import io
import math
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from app.core.native_image_admission import bounded_native_image
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import UploadValidator, ValidatedUpload

MAX_PUBLIC_PDF_BYTES = 2 * 1024 * 1024
PDF_RENDER_TIMEOUT_SECONDS = 15
PDF_RENDER_MAX_DIMENSION = 2500
PDF_RENDER_MAX_PIXELS = 6_250_000
PDF_RENDER_MEMORY_BYTES = 384 * 1024 * 1024
_PDF_ERRORS = {
    2: "PDF files must contain exactly one page.",
    3: "Password-protected PDFs are not supported. Please upload an unlocked single-page PDF.",
    4: "The PDF could not be read. Please upload a valid single-page PDF.",
    5: "The PDF page has invalid dimensions.",
}


@bounded_native_image
def render_single_page_pdf_isolated(content: bytes) -> ValidatedUpload:
    """Kill stalled native parsers; the parent owns the cross-process image slot."""
    if not content.startswith(b"%PDF-"):
        raise ImageValidationError(_PDF_ERRORS[4])
    if len(content) > MAX_PUBLIC_PDF_BYTES:
        raise ImageValidationError("PDF files must be 2 MB or smaller.")
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.infrastructure.security.public_upload_pdf"],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=PDF_RENDER_TIMEOUT_SECONDS,
            check=False,
            cwd=Path(__file__).resolve().parents[3],
            creationflags=creation_flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ImageValidationError("The PDF took too long to read. Please use a simpler single-page PDF or an image.") from exc
    if result.returncode != 0:
        raise ImageValidationError(_PDF_ERRORS.get(result.returncode, _PDF_ERRORS[4]))
    from PIL import Image

    with Image.open(io.BytesIO(result.stdout)) as image:
        width, height = image.size
    return ValidatedUpload(
        content=result.stdout, content_type="image/jpeg", filename="page.jpg",
        width=width, height=height, format="JPEG",
    )


def _render_worker(content: bytes) -> tuple[int, bytes]:
    """No external resources, JavaScript, or PDF attachments enter the output."""
    import pypdfium2
    from pypdf import PdfReader

    if len(content) > MAX_PUBLIC_PDF_BYTES or not content.startswith(b"%PDF-"):
        return 4, b""
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            return 3, b""
        if len(reader.pages) != 1:
            return 2, b""
        with pypdfium2.PdfDocument(content) as document:
            if len(document) != 1:
                return 2, b""
            with closing(document[0]) as page:
                width, height = page.get_size()
                if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                    return 5, b""
                scale = min(200 / 72, PDF_RENDER_MAX_DIMENSION / max(width, height))
                while math.ceil(width * scale) * math.ceil(height * scale) > PDF_RENDER_MAX_PIXELS:
                    scale *= 0.99
                with closing(page.render(scale=scale, fill_color=(255, 255, 255, 255))) as bitmap:
                    with bitmap.to_pil() as image:
                        with UploadValidator._to_rgb(image) as rgb:
                            return 0, UploadValidator._encode_jpeg(rgb)
    except Exception:
        return 4, b""


def _main() -> None:
    try:
        import resource

        setrlimit = getattr(resource, "setrlimit")
        setrlimit(getattr(resource, "RLIMIT_AS"), (PDF_RENDER_MEMORY_BYTES, PDF_RENDER_MEMORY_BYTES))
        setrlimit(getattr(resource, "RLIMIT_CPU"), (PDF_RENDER_TIMEOUT_SECONDS, PDF_RENDER_TIMEOUT_SECONDS))
    except (ImportError, OSError, ValueError):
        # Windows still has source/pixel bounds and the parent-enforced deadline.
        pass
    code, output = _render_worker(sys.stdin.buffer.read(MAX_PUBLIC_PDF_BYTES + 1))
    if code == 0:
        sys.stdout.buffer.write(output)
    raise SystemExit(code)


if __name__ == "__main__":
    _main()
