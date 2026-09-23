from __future__ import annotations

import io
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image, ImageOps

os.environ.setdefault("APP_SECRET_KEY", "unit-test-secret")

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_validator import (
    DisabledDocumentIngestionScanner,
    DisabledMalwareScanner,
    MalwareScannerConfigurationError,
    UploadValidator,
    assert_malware_scanner_ready,
    malware_scanner_from_settings,
)


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

    def test_optional_size_bound_precedes_orientation_and_rgb_pixel_copies(self) -> None:
        source = io.BytesIO()
        with Image.new("RGBA", (1600, 800), (255, 0, 0, 128)) as image:
            image.save(source, format="PNG")
        observed_sizes = []
        original_transpose = ImageOps.exif_transpose

        def inspect_transpose(image):
            observed_sizes.append(image.size)
            return original_transpose(image)

        scanner = RecordingScanner()
        with patch(
            "app.infrastructure.security.upload_validator.ImageOps.exif_transpose",
            inspect_transpose,
        ):
            result = UploadValidator(scanner=scanner).validate(
                content=source.getvalue(),
                filename="back.png",
                declared_content_type="image/png",
                max_dimension=400,
            )
        self.assertEqual(scanner.calls, 1)
        self.assertEqual(observed_sizes, [(400, 200)])
        with Image.open(io.BytesIO(result.content)) as prepared:
            self.assertEqual(prepared.size, (400, 200))
            self.assertEqual(prepared.mode, "RGB")

    def test_default_validation_retains_original_image_dimensions(self) -> None:
        source = io.BytesIO()
        with Image.new("RGB", (1600, 800), "white") as image:
            image.save(source, format="JPEG")
        result = UploadValidator().validate(
            content=source.getvalue(), filename="back.jpg", declared_content_type="image/jpeg"
        )
        with Image.open(io.BytesIO(result.content)) as prepared:
            self.assertEqual(prepared.size, (1600, 800))

    def test_optional_size_bound_does_not_bypass_original_pixel_limit(self) -> None:
        validator = UploadValidator()
        validator._settings = validator._settings.model_copy(update={"upload_max_pixels": 1_000})
        with self.assertRaises(ImageValidationError):
            validator.validate(
                content=self._png(),
                filename="back.png",
                declared_content_type="image/png",
                max_dimension=16,
            )

    def test_optional_size_bound_still_rejects_truncated_original(self) -> None:
        source = self._png()
        with self.assertRaises(ImageValidationError):
            UploadValidator().validate(
                content=source[: len(source) // 2],
                filename="back.png",
                declared_content_type="image/png",
                max_dimension=16,
            )

    def test_accepts_real_png_and_sanitizes_filename(self) -> None:
        result = UploadValidator().validate(
            content=self._png(),
            filename="../unsafe passport!!.jpg",
            declared_content_type="application/octet-stream",
        )

        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.filename, "unsafe-passport.jpg")
        self.assertEqual(result.format, "JPEG")
        self.assertTrue(result.content.startswith(b"\xff\xd8\xff"))
        self.assertEqual(result.width, 64)
        self.assertEqual(result.height, 32)

    def test_uses_decoded_content_instead_of_declared_mime_or_extension(self) -> None:
        result = UploadValidator().validate(
            content=self._png(),
            filename="phone-capture.heic",
            declared_content_type="image/heic",
        )

        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.filename, "phone-capture.jpg")
        with Image.open(io.BytesIO(result.content)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (64, 32))

    def test_canonicalizes_common_decodable_mobile_and_desktop_formats(self) -> None:
        for source_format, filename in (
            ("BMP", "passport.bmp"),
            ("TIFF", "passport.tiff"),
            ("WEBP", "passport.webp"),
        ):
            with self.subTest(source_format=source_format):
                source = io.BytesIO()
                Image.new("RGB", (48, 24), "white").save(source, format=source_format)
                result = UploadValidator().validate(
                    content=source.getvalue(),
                    filename=filename,
                    declared_content_type="application/octet-stream",
                )

                self.assertEqual(result.content_type, "image/jpeg")
                self.assertEqual(result.filename, "passport.jpg")
                self.assertTrue(result.content.startswith(b"\xff\xd8\xff"))

    def test_decodes_real_heif_and_canonicalizes_it_to_jpeg(self) -> None:
        try:
            import pillow_heif
        except ImportError:
            self.skipTest("pillow-heif is not installed in this host test environment")

        source = io.BytesIO()
        pillow_heif.from_pillow(Image.new("RGB", (80, 40), "white")).save(source, quality=90)

        result = UploadValidator().validate(
            content=source.getvalue(),
            filename="iphone-passport.heic",
            declared_content_type="image/heic",
        )

        self.assertEqual(result.content_type, "image/jpeg")
        self.assertEqual(result.filename, "iphone-passport.jpg")
        self.assertTrue(result.content.startswith(b"\xff\xd8\xff"))
        with Image.open(io.BytesIO(result.content)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (80, 40))

    def test_rejects_truncated_image_after_header(self) -> None:
        source = self._png()
        with self.assertRaises(ImageValidationError):
            UploadValidator().validate(
                content=source[: len(source) // 2],
                filename="passport.png",
                declared_content_type="image/png",
            )

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

    def test_production_ingestion_cannot_start_without_scanner(self) -> None:
        settings = SimpleNamespace(
            is_development=False,
            untrusted_document_ingestion_enabled=True,
            malware_scanner_enabled=False,
        )

        with self.assertRaises(MalwareScannerConfigurationError):
            assert_malware_scanner_ready(settings)

    def test_production_startup_requires_live_scanner_pong(self) -> None:
        settings = SimpleNamespace(
            is_development=False,
            untrusted_document_ingestion_enabled=True,
            malware_scanner_enabled=True,
            malware_scanner_host="scanner.internal",
            malware_scanner_port=3310,
            malware_scanner_timeout_seconds=1.0,
        )

        with patch(
            "app.infrastructure.security.upload_validator.socket.create_connection",
            side_effect=OSError("scanner offline"),
        ):
            with self.assertRaises(MalwareScannerConfigurationError):
                assert_malware_scanner_ready(settings)

    def test_disabled_scanner_is_explicitly_development_only(self) -> None:
        development = SimpleNamespace(
            is_development=True,
            untrusted_document_ingestion_enabled=True,
            malware_scanner_enabled=False,
        )
        document_free = SimpleNamespace(
            is_development=False,
            untrusted_document_ingestion_enabled=False,
            malware_scanner_enabled=False,
        )

        self.assertIsInstance(
            malware_scanner_from_settings(development),
            DisabledMalwareScanner,
        )
        self.assertIsInstance(
            malware_scanner_from_settings(document_free),
            DisabledDocumentIngestionScanner,
        )


if __name__ == "__main__":
    unittest.main()
