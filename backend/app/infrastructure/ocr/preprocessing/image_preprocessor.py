"""Side-effect-free image preparation used by OCR extraction."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass

from PIL import Image, ImageFilter, ImageOps


@dataclass(frozen=True)
class ImageQualityAssessment:
    score: float
    sharpness: float
    brightness: float
    contrast: float
    width: int
    height: int

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


class OCRImagePreprocessor:
    """Normalizes uploads and produces deterministic OCR variants."""

    def normalize(self, file_content: bytes) -> bytes:
        with Image.open(io.BytesIO(file_content)) as raw_image:
            image = ImageOps.exif_transpose(raw_image).convert("RGB")
            max_dimension = max(image.size)
            if max_dimension > 2200:
                scale = 2200 / max_dimension
                image = image.resize(
                    (
                        max(1, round(image.size[0] * scale)),
                        max(1, round(image.size[1] * scale)),
                    )
                )

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=92, optimize=True)
            return buffer.getvalue()

    def assess_quality(self, image_bytes: bytes) -> ImageQualityAssessment:
        import numpy as np

        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            gray = ImageOps.grayscale(ImageOps.exif_transpose(raw_image))
            array = np.asarray(gray, dtype=np.float32)
            width, height = gray.size

        brightness = float(array.mean() / 255.0)
        contrast = min(1.0, float(array.std() / 64.0))
        try:
            import cv2

            sharpness_raw = float(cv2.Laplacian(array, cv2.CV_32F).var())
        except Exception:
            horizontal = np.abs(np.diff(array, axis=1)).mean() if width > 1 else 0.0
            vertical = np.abs(np.diff(array, axis=0)).mean() if height > 1 else 0.0
            sharpness_raw = float(horizontal + vertical) * 10
        sharpness = min(1.0, sharpness_raw / 500.0)
        exposure = max(0.0, 1.0 - abs(brightness - 0.55) / 0.55)
        resolution = min(1.0, (width * height) / 1_200_000)
        score = (sharpness * 0.4) + (exposure * 0.25) + (contrast * 0.2) + (resolution * 0.15)
        return ImageQualityAssessment(
            score=round(max(0.0, min(1.0, score)), 3),
            sharpness=round(sharpness, 3),
            brightness=round(brightness, 3),
            contrast=round(contrast, 3),
            width=width,
            height=height,
        )

    def tesseract_jobs(self, image_bytes: bytes) -> list[tuple[Image.Image, str]]:
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            base = ImageOps.exif_transpose(raw_image).convert("RGB")
            base.thumbnail((1800, 1800))
            gray = ImageOps.autocontrast(ImageOps.grayscale(base))
            width, height = gray.size
            mrz_crop = gray.crop((0, int(height * 0.66), width, height))
            full_config = "--oem 1 --psm 6"
            mrz_config = (
                "--oem 1 --psm 6 "
                "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            )
            jobs = [
                (gray, full_config),
                (self.upscale(gray, 2), full_config),
                (self.threshold(gray), full_config),
                (self.upscale(mrz_crop, 3), mrz_config),
                (self.threshold(self.upscale(mrz_crop, 3)), mrz_config),
            ]
            return [(image.copy(), config) for image, config in jobs]

    def mrz_tesseract_jobs(self, image_bytes: bytes) -> list[tuple[Image.Image, str, str]]:
        """Return a small, ordered MRZ-only job set for the fast path.

        This intentionally avoids full-page OCR and expensive denoising. The MRZ
        is high-contrast OCR-B text at the bottom of TD3 passports, so a few
        targeted crops are both faster and more accurate than broad ensemble OCR.
        """
        with Image.open(io.BytesIO(image_bytes)) as raw_image:
            base = ImageOps.exif_transpose(raw_image).convert("RGB")
            base.thumbnail((1800, 1800))
            gray = ImageOps.autocontrast(ImageOps.grayscale(base))
            width, height = gray.size
            bands = (
                ("mrz_bottom_34", 0.66),
                ("mrz_bottom_42", 0.58),
            )
            config = (
                "--oem 1 --psm 6 "
                "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789< "
                "-c load_system_dawg=0 -c load_freq_dawg=0"
            )
            jobs: list[tuple[Image.Image, str, str]] = []
            for variant_name, top_ratio in bands:
                crop = gray.crop((0, int(height * top_ratio), width, height))
                jobs.append((self.upscale(crop, 3), config, f"{variant_name}_gray"))
                jobs.append((self.threshold(self.upscale(crop, 3)), config, f"{variant_name}_threshold"))
            return [(image.copy(), config, variant_name) for image, config, variant_name in jobs]

    def roi_variants(self, crop: Image.Image) -> list[Image.Image]:
        gray = ImageOps.autocontrast(ImageOps.grayscale(crop))
        return [
            gray,
            gray.filter(ImageFilter.SHARPEN),
            ImageOps.autocontrast(gray, cutoff=2),
            self.threshold(gray),
            self.clahe(gray),
            self.denoise(gray),
        ]

    def upscale(self, image: Image.Image, factor: int) -> Image.Image:
        resized = image.resize((image.width * factor, image.height * factor))
        return resized.filter(ImageFilter.SHARPEN)

    def threshold(self, image: Image.Image) -> Image.Image:
        try:
            import cv2
            import numpy as np

            thresholded = cv2.adaptiveThreshold(
                np.asarray(image),
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9,
            )
            return Image.fromarray(thresholded)
        except Exception:
            return image.point(lambda pixel: 255 if pixel > 150 else 0)

    def clahe(self, image: Image.Image) -> Image.Image:
        try:
            import cv2
            import numpy as np

            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return Image.fromarray(clahe.apply(np.asarray(image)))
        except Exception:
            return image

    def denoise(self, image: Image.Image) -> Image.Image:
        try:
            import cv2
            import numpy as np

            denoised = cv2.fastNlMeansDenoising(
                np.asarray(image),
                None,
                h=8,
                templateWindowSize=7,
                searchWindowSize=21,
            )
            return Image.fromarray(denoised)
        except Exception:
            return image
