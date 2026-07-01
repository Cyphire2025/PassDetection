from __future__ import annotations

import io
import os
import unittest

from PIL import Image

os.environ.setdefault("APP_SECRET_KEY", "unit-test-secret")

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import UploadValidator


class RecordingScanner:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def scan(self, content: bytes) -> None:
        self.calls += 1
        if self.fail:
            raise ImageValidationError("Uploaded file failed security scanning")


class UploadValidatorTests(unittest.TestCase):
    def _png(self) -> bytes:
        buffer = io.BytesIO()
        Image.new("RGB", (64, 32), "white").save(buffer, format="PNG")
        return buffer.getvalue()

    def test_accepts_real_png_and_sanitizes_filename(self) -> None:
        result = UploadValidator().validate(
            content=self._png(),
            filename="../unsafe passport!!.jpg",
            declared_content_type="application/octet-stream",
        )

        self.assertEqual(result.content_type, "image/png")
        self.assertEqual(result.filename, "unsafe-passport.png")
        self.assertEqual(result.width, 64)
        self.assertEqual(result.height, 32)

    def test_rejects_non_image_payload_even_if_declared_image(self) -> None:
        with self.assertRaises(ImageValidationError):
            UploadValidator().validate(
                content=b"not-an-image",
                filename="passport.jpg",
                declared_content_type="image/jpeg",
            )

    def test_invokes_configured_malware_scanner(self) -> None:
        scanner = RecordingScanner()

        UploadValidator(scanner=scanner).validate(
            content=self._png(),
            filename="passport.png",
            declared_content_type="image/png",
        )

        self.assertEqual(scanner.calls, 1)

    def test_rejects_upload_when_malware_scanner_fails(self) -> None:
        with self.assertRaises(ImageValidationError):
            UploadValidator(scanner=RecordingScanner(fail=True)).validate(
                content=self._png(),
                filename="passport.png",
                declared_content_type="image/png",
            )


if __name__ == "__main__":
    unittest.main()
