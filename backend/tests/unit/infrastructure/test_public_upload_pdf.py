from __future__ import annotations

import io
import subprocess
from unittest.mock import AsyncMock, Mock

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security import public_upload_pdf
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService


def _pdf(*, pages: int = 1, encrypted: bool = False, width: int = 300, height: int = 400) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=width, height=height)
    if encrypted:
        writer.encrypt("synthetic-password")
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def _service() -> UploadSecurityService:
    service = UploadSecurityService(scanner=Mock(), storage=Mock())
    service._record = AsyncMock()
    return service


async def _validate(service: UploadSecurityService, content: bytes, filename: str = "page.pdf"):
    return await service.validate_public_file(
        content=content, filename=filename, declared_content_type=None,
        context=UploadSecurityContext(ingestion_flow="public_passport_upload"),
    )


async def test_single_page_pdf_normalizes_to_safe_jpeg_and_scans_original_bytes():
    source = _pdf()
    service = _service()
    normalized = await _validate(service, source, "../private page.pdf")
    assert normalized.content_type == "image/jpeg"
    assert normalized.filename == "private-page.jpg"
    with Image.open(io.BytesIO(normalized.content)) as image:
        assert image.format == "JPEG"
        assert image.width > 300
        assert image.height > 400
        assert image.mode == "RGB"
    service._scanner.scan.assert_called_once_with(source)
    record = service._record.call_args.kwargs
    assert record["content"] == source
    assert record["disposition"] == "accepted"


@pytest.mark.parametrize(
    ("source", "message"),
    [(_pdf(pages=0), "exactly one page"), (_pdf(pages=2), "exactly one page"),
     (_pdf(encrypted=True), "Password-protected"), (b"%PDF-1.4\nbroken", "could not be read")],
)
async def test_public_pdf_rejects_invalid_page_count_password_and_malformed_content(source, message):
    service = _service()
    with pytest.raises(ImageValidationError, match=message):
        await _validate(service, source)
    assert service._record.call_args.kwargs["disposition"] == "rejected"


async def test_public_pdf_size_limit_cannot_be_bypassed_using_jpeg_filename():
    service = _service()
    source = _pdf() + b" " * public_upload_pdf.MAX_PUBLIC_PDF_BYTES
    with pytest.raises(ImageValidationError, match="2 MB"):
        await _validate(service, source, "pretend.jpg")
    service._scanner.scan.assert_not_called()


async def test_public_pdf_accepts_exact_existing_two_mib_boundary():
    source = _pdf()
    source += b" " * (public_upload_pdf.MAX_PUBLIC_PDF_BYTES - len(source))
    result = await _validate(_service(), source)
    assert result.content_type == "image/jpeg"


async def test_public_pdf_large_page_raster_stays_within_pixel_and_dimension_limits():
    result = await _validate(_service(), _pdf(width=6400, height=12800))
    assert max(result.width, result.height) <= public_upload_pdf.PDF_RENDER_MAX_DIMENSION
    assert result.width * result.height <= public_upload_pdf.PDF_RENDER_MAX_PIXELS


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "HEIF", "AVIF"])
async def test_public_allowed_image_formats_normalize_to_jpeg(image_format):
    source = io.BytesIO()
    with Image.new("RGB", (120, 160), "white") as image:
        image.save(source, format=image_format)
    result = await _validate(_service(), source.getvalue(), "page." + image_format.lower())
    assert result.content_type == "image/jpeg"


@pytest.mark.parametrize("image_format", ["WEBP", "BMP", "TIFF", "GIF"])
async def test_public_removed_image_formats_rejected_even_with_allowed_filename(image_format):
    source = io.BytesIO()
    with Image.new("RGB", (120, 160), "white") as image:
        image.save(source, format=image_format)
    with pytest.raises(ImageValidationError, match="Unsupported file format"):
        await _validate(_service(), source.getvalue(), "misleading.png")


def test_stalled_pdf_parser_fails_closed(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("synthetic", 15)
    monkeypatch.setattr(public_upload_pdf.subprocess, "run", timeout)
    with pytest.raises(ImageValidationError, match="too long"):
        public_upload_pdf.render_single_page_pdf_isolated(_pdf())


def _photo_pdf(*, page_size=(792, 612), rotation=0):
    """A synthetic red image on white paper, without any identity data."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=page_size[0], height=page_size[1])
    page.rotation = rotation
    image = DecodedStreamObject()
    image.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(20),
        NameObject("/Height"): NumberObject(30),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
    })
    image.set_data(bytes((220, 20, 20)) * 20 * 30)
    image_ref = writer._add_object(image.flate_encode())
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Photo"): image_ref}),
    })
    contents = DecodedStreamObject()
    contents.set_data(b"q 300 0 0 420 156 96 cm /Photo Do Q\n")
    page[NameObject("/Contents")] = writer._add_object(contents)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


@pytest.mark.parametrize(
    ("page_size", "rotation"),
    [((792, 612), 0), ((612, 792), 0), ((600, 600), 0), ((792, 612), 90)],
)
def test_pdf_preview_preserves_full_page_layout_and_rotation(page_size, rotation):
    preview = public_upload_pdf.render_single_page_pdf_isolated(
        _photo_pdf(page_size=page_size, rotation=rotation),
    )
    expected_width, expected_height = page_size if rotation == 0 else page_size[::-1]
    assert preview.width / preview.height == pytest.approx(expected_width / expected_height, abs=0.002)
    with Image.open(io.BytesIO(preview.content)) as image:
        # The paper margins remain even when the PDF contains one portrait.
        assert min(image.getpixel((5, 5))) > 240
