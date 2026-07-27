from __future__ import annotations

import io
import math

import pytest
from PIL import Image

from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    inspect_passport_image,
    render_passport_image_crop,
    render_passport_image_thumbnail,
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


def test_renderer_accepts_per_degree_rotation() -> None:
    rendered = render_passport_image_crop(
        _jpeg(),
        x=0.0,
        y=0.0,
        width=1.0,
        height=1.0,
        rotation_degrees=37,
    )

    assert rendered.source_width > 400
    assert rendered.source_height > 300
    assert (rendered.output_width, rendered.output_height) == (
        rendered.source_width,
        rendered.source_height,
    )
    assert inspect_passport_image(_jpeg(), rotation_degrees=37) == (
        rendered.source_width,
        rendered.source_height,
    )


@pytest.mark.parametrize("rotation_degrees", (-1, 360, 45.5, True))
def test_renderer_rejects_rotation_outside_whole_degree_range(
    rotation_degrees: int | float | bool,
) -> None:
    with pytest.raises(PassportImageCropError, match="whole number"):
        render_passport_image_crop(
            _jpeg(),
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=rotation_degrees,
        )


def test_thumbnail_renderer_bounds_dimensions_and_strips_metadata() -> None:
    rendered = render_passport_image_thumbnail(
        _jpeg(1200, 600, orientation=1),
        max_dimension=320,
    )

    assert rendered.content_type == "image/jpeg"
    assert (rendered.width, rendered.height) == (320, 160)
    with Image.open(io.BytesIO(rendered.content)) as result:
        assert result.size == (320, 160)
        assert result.getexif() == {}


def test_renderer_applies_bounded_sharpness_and_strips_metadata() -> None:
    source = Image.new("RGB", (120, 120), "white")
    for offset in range(40, 80):
        source.putpixel((offset, 60), (30, 30, 30))
    output = io.BytesIO()
    source.save(output, format="JPEG", quality=95)
    source.close()

    normal = render_passport_image_crop(
        output.getvalue(),
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=1,
    )
    sharpened = render_passport_image_crop(
        output.getvalue(),
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=3,
    )

    assert sharpened.content != normal.content
    with Image.open(io.BytesIO(sharpened.content)) as result:
        assert result.size == (120, 120)
        assert result.getexif() == {}


def test_strong_100_percent_matches_legacy_300_percent() -> None:
    source = Image.new("RGB", (120, 120), "white")
    for offset in range(30, 90):
        source.putpixel((offset, 60), (20, 20, 20))
    output = io.BytesIO()
    source.save(output, format="JPEG", quality=95)
    source.close()

    legacy_maximum = render_passport_image_crop(
        output.getvalue(),
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=3,
        sharpness_algorithm_version=1,
    )
    strong_minimum = render_passport_image_crop(
        output.getvalue(),
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=1,
        sharpness_algorithm_version=2,
    )

    assert strong_minimum.content == legacy_maximum.content


def test_renderer_rejects_unknown_sharpness_algorithm() -> None:
    with pytest.raises(PassportImageCropError, match="algorithm version"):
        render_passport_image_crop(
            _jpeg(),
            x=0,
            y=0,
            width=1,
            height=1,
            rotation_degrees=0,
            sharpness_algorithm_version=3,
        )


@pytest.mark.parametrize("sharpness", (0.99, 3.01, math.inf))
def test_renderer_rejects_out_of_range_sharpness(sharpness: float) -> None:
    with pytest.raises(PassportImageCropError, match="Sharpness|finite"):
        render_passport_image_crop(
            _jpeg(),
            x=0,
            y=0,
            width=1,
            height=1,
            rotation_degrees=0,
            sharpness=sharpness,
        )
