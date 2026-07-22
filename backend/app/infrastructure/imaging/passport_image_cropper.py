"""Bounded, deterministic rendering for non-destructive passport crops."""

from __future__ import annotations

import io
import math
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config.settings import get_settings
from app.domain.value_objects.passport_image_crop import PassportImageCrop

MIN_NORMALIZED_CROP_SIZE = 0.08
MIN_RENDERED_CROP_PIXELS = 32
SUPPORTED_ROTATIONS = frozenset({0, 90, 180, 270})


class PassportImageCropError(ValueError):
    """Raised when crop metadata or source pixels cannot be processed safely."""


@dataclass(frozen=True, slots=True)
class RenderedPassportImage:
    content: bytes
    content_type: str
    extension: str
    source_width: int
    source_height: int
    output_width: int
    output_height: int


@dataclass(frozen=True, slots=True)
class RenderedPassportThumbnail:
    content: bytes
    content_type: str
    width: int
    height: int


def inspect_passport_image(content: bytes, *, rotation_degrees: int = 0) -> tuple[int, int]:
    """Return canonical dimensions after the requested clockwise rotation."""

    image = _open_canonical_image(content)
    try:
        if rotation_degrees not in SUPPORTED_ROTATIONS:
            raise PassportImageCropError("Choose a supported image rotation.")
        if rotation_degrees in {90, 270}:
            return image.height, image.width
        return image.width, image.height
    finally:
        image.close()


def render_passport_image_crop(
    content: bytes,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    rotation_degrees: int,
) -> RenderedPassportImage:
    """Rotate then crop canonical source pixels and emit metadata-free JPEG."""

    _validate_normalized_crop(
        x=x,
        y=y,
        width=width,
        height=height,
        rotation_degrees=rotation_degrees,
    )
    image = _open_canonical_image(content)
    rotated: Image.Image | None = None
    cropped: Image.Image | None = None
    rgb: Image.Image | None = None
    try:
        rotated = (
            image.copy() if rotation_degrees == 0 else image.rotate(-rotation_degrees, expand=True)
        )
        source_width, source_height = rotated.size
        left = max(0, min(source_width - 1, math.floor(x * source_width)))
        top = max(0, min(source_height - 1, math.floor(y * source_height)))
        right = max(left + 1, min(source_width, math.ceil((x + width) * source_width)))
        bottom = max(top + 1, min(source_height, math.ceil((y + height) * source_height)))
        output_width = right - left
        output_height = bottom - top
        if output_width < MIN_RENDERED_CROP_PIXELS or output_height < MIN_RENDERED_CROP_PIXELS:
            raise PassportImageCropError(
                "The crop area is too small. Select a larger part of the image."
            )
        cropped = rotated.crop((left, top, right, bottom))
        rgb = _to_rgb(cropped)
        output = io.BytesIO()
        rgb.save(
            output,
            format="JPEG",
            quality=93,
            optimize=True,
            progressive=True,
        )
        return RenderedPassportImage(
            content=output.getvalue(),
            content_type="image/jpeg",
            extension=".jpg",
            source_width=source_width,
            source_height=source_height,
            output_width=output_width,
            output_height=output_height,
        )
    finally:
        if rgb is not None:
            rgb.close()
        if cropped is not None:
            cropped.close()
        if rotated is not None:
            rotated.close()
        image.close()


def render_saved_passport_image_crop(
    content: bytes,
    crop: PassportImageCrop,
) -> RenderedPassportImage:
    """Render a persisted crop, rejecting changed source geometry."""

    rendered = render_passport_image_crop(
        content,
        x=crop.x,
        y=crop.y,
        width=crop.width,
        height=crop.height,
        rotation_degrees=crop.rotation_degrees,
    )
    if rendered.source_width != crop.source_width or rendered.source_height != crop.source_height:
        raise PassportImageCropError(
            "The source image changed after this crop was saved. Reset and crop it again."
        )
    return rendered


def render_passport_image_thumbnail(
    content: bytes,
    *,
    max_dimension: int,
) -> RenderedPassportThumbnail:
    """Render a bounded, metadata-free JPEG for authenticated list views."""

    if max_dimension < 1:
        raise PassportImageCropError("Thumbnail dimensions must be positive.")
    image = _open_canonical_image(content)
    rgb: Image.Image | None = None
    try:
        image.thumbnail(
            (max_dimension, max_dimension),
            Image.Resampling.LANCZOS,
        )
        rgb = _to_rgb(image)
        output = io.BytesIO()
        rgb.save(
            output,
            format="JPEG",
            quality=82,
            optimize=True,
            progressive=True,
        )
        return RenderedPassportThumbnail(
            content=output.getvalue(),
            content_type="image/jpeg",
            width=rgb.width,
            height=rgb.height,
        )
    finally:
        if rgb is not None:
            rgb.close()
        image.close()


def _open_canonical_image(content: bytes) -> Image.Image:
    if not content:
        raise PassportImageCropError("The stored image is empty.")
    settings = get_settings()
    if len(content) > settings.upload_max_file_size_bytes:
        raise PassportImageCropError("The stored image file is too large.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as opened:
                width, height = opened.size
                if width <= 0 or height <= 0:
                    raise PassportImageCropError("The stored image dimensions are invalid.")
                if width * height > settings.upload_max_pixels:
                    raise PassportImageCropError("The stored image resolution is too large.")
                opened.seek(0)
                opened.load()
                canonical = ImageOps.exif_transpose(opened).copy()
    except PassportImageCropError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise PassportImageCropError("The stored image is not readable.") from exc
    return canonical


def _validate_normalized_crop(
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    rotation_degrees: int,
) -> None:
    values = (x, y, width, height)
    if not all(math.isfinite(value) for value in values):
        raise PassportImageCropError("Crop coordinates must be finite numbers.")
    if rotation_degrees not in SUPPORTED_ROTATIONS:
        raise PassportImageCropError("Choose a supported image rotation.")
    if x < 0 or y < 0 or x > 1 or y > 1:
        raise PassportImageCropError("Crop coordinates must stay inside the image.")
    if width < MIN_NORMALIZED_CROP_SIZE or height < MIN_NORMALIZED_CROP_SIZE:
        raise PassportImageCropError(
            "Crop width and height must each cover at least 8% of the image."
        )
    if x + width > 1.000001 or y + height > 1.000001:
        raise PassportImageCropError("Crop coordinates must stay inside the image.")


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        try:
            return Image.alpha_composite(background, rgba).convert("RGB")
        finally:
            rgba.close()
            background.close()
    return image.convert("RGB")
