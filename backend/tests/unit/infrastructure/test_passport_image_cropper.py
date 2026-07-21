from __future__ import annotations

import io
import math

import pytest
from PIL import Image

from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    inspect_passport_image,
    render_passport_image_crop,
)


def _jpeg(width: int = 400, height: int = 300, *, orientation: int | None = None) -> bytes:
    image = Image.new("RGB", (width, height), "navy")
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[274] = orientation
    image.save(output, format="JPEG", quality=90, exif=exif)
    image.close()
    return output.getvalue()


def test_renderer_rotates_then_crops_in_normalized_source_coordinates() -> None:
    rendered = render_passport_image_crop(
        _jpeg(400, 300),
        x=0.25,
        y=0.25,
        width=0.5,
        height=0.5,
        rotation_degrees=90,
    )
    assert (rendered.source_width, rendered.source_height) == (300, 400)
    assert (rendered.output_width, rendered.output_height) == (150, 200)
    assert rendered.content_type == "image/jpeg"
    assert rendered.extension == ".jpg"
    with Image.open(io.BytesIO(rendered.content)) as result:
        assert result.size == (150, 200)


def test_renderer_honors_exif_orientation_before_editor_rotation() -> None:
    assert inspect_passport_image(_jpeg(120, 80, orientation=6)) == (80, 120)
    assert inspect_passport_image(
        _jpeg(120, 80, orientation=6),
        rotation_degrees=90,
    ) == (120, 80)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"x": math.nan, "y": 0.0, "width": 1.0, "height": 1.0}, "finite"),
        ({"x": 0.0, "y": 0.0, "width": 0.07, "height": 1.0}, "8%"),
        ({"x": 0.9, "y": 0.0, "width": 0.2, "height": 1.0}, "inside"),
    ],
)
def test_renderer_rejects_non_finite_tiny_or_out_of_bounds_crops(
    kwargs: dict[str, float],
    message: str,
) -> None:
    with pytest.raises(PassportImageCropError, match=message):
        render_passport_image_crop(
            _jpeg(),
            rotation_degrees=0,
            **kwargs,
        )


def test_renderer_rejects_crop_below_pixel_floor() -> None:
    with pytest.raises(PassportImageCropError, match="too small"):
        render_passport_image_crop(
            _jpeg(200, 200),
            x=0.0,
            y=0.0,
            width=0.08,
            height=0.08,
            rotation_degrees=0,
        )


def test_renderer_rejects_unknown_rotation() -> None:
    with pytest.raises(PassportImageCropError, match="rotation"):
        render_passport_image_crop(
            _jpeg(),
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=45,
        )
