from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security import upload_security


@pytest.mark.parametrize("kind", ["valid", "encrypted", "malformed"])
def test_pdf_structure_validation_closes_its_stream_on_every_outcome(monkeypatch, kind):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if kind == "encrypted":
        writer.encrypt("synthetic-test-password")
    output = io.BytesIO()
    writer.write(output)
    content = output.getvalue() if kind != "malformed" else b"%PDF-1.4 unreadable"
    streams = []
    original = upload_security.PdfReader

    def reader(stream, **arguments):
        streams.append(stream)
        return original(stream, **arguments)

    monkeypatch.setattr(upload_security, "PdfReader", reader)
    if kind == "valid":
        upload_security._validate_pdf_structure(content)
    else:
        with pytest.raises(ImageValidationError):
            upload_security._validate_pdf_structure(content)
    assert len(streams) == 1
    assert streams[0].closed
