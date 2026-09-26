"""Compare the memory-safe renderer with the previously shipped pixel pipeline.

The reference deliberately retains the old ordering/copies. This is a byte-level
compatibility oracle for existing saved crops, EXIF orientation and alpha edges.
"""
from __future__ import annotations

import io
import math
from functools import lru_cache

import pytest
from PIL import Image, ImageEnhance, ImageOps

from app.infrastructure.imaging.passport_image_cropper import render_passport_image_crop
from app.infrastructure.security.upload_validator import DisabledMalwareScanner, UploadValidator


@lru_cache(maxsize=64)
def _fixture(mode: str, orientation: int) -> bytes:
    with Image.new("RGBA", (192, 128)) as base:
        base.putdata([((x * 13 + y) % 256, (x + y * 17) % 256,
                       (x * 7 + y * 3) % 256, (x * 19 + y * 11) % 256)
                      for y in range(128) for x in range(192)])
        picture = base.convert(mode)
    try:
        exif = Image.Exif()
        exif[274] = orientation
        exif[315] = "synthetic-private-author-must-not-survive"
        if mode == "P":
            picture.info["transparency"] = 0
        output = io.BytesIO()
        picture.save(output, format="JPEG" if mode == "CMYK" else "PNG", exif=exif)
        return output.getvalue()
    finally:
        picture.close()


def _legacy_rgb(image: Image.Image) -> Image.Image:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        with image.convert("RGBA") as rgba, Image.new("RGBA", image.size, "white") as background:
            with Image.alpha_composite(background, rgba) as composite:
                return composite.convert("RGB")
    return image.convert("RGB")


def _legacy_upload(content: bytes, maximum: int | None) -> bytes:
    with Image.open(io.BytesIO(content)) as opened:
        opened.load()
        if maximum:
            opened.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
        with ImageOps.exif_transpose(opened) as oriented, _legacy_rgb(oriented) as rgb:
            output = io.BytesIO()
            rgb.save(output, format="JPEG", quality=94, optimize=True, progressive=True)
            return output.getvalue()


def _legacy_crop(content: bytes, rotation: int, sharpness: float, version: int,
                 partial: bool) -> tuple[bytes, tuple[int, int], tuple[int, int]]:
    with Image.open(io.BytesIO(content)) as opened:
        opened.load()
        with ImageOps.exif_transpose(opened) as oriented:
            canonical = oriented.copy()
    rotated = cropped = rgb = None
    try:
        if rotation == 0:
            rotated = canonical.copy()
        elif rotation in {90, 180, 270}:
            rotated = canonical.rotate(-rotation, expand=True)
        else:
            rotated = canonical.rotate(-rotation, resample=Image.Resampling.BICUBIC,
                                       expand=True, fillcolor="white")
        width, height = rotated.size
        x, y, crop_width, crop_height = (0.125, 0.125, 0.75, 0.75) if partial else (0, 0, 1, 1)
        box = (math.floor(x * width), math.floor(y * height),
               math.ceil((x + crop_width) * width), math.ceil((y + crop_height) * height))
        cropped = rotated.crop(box)
        rgb = _legacy_rgb(cropped)
        factor = 3 + ((sharpness - 1) * 2) if version == 2 else sharpness
        if factor != 1:
            sharpened = ImageEnhance.Sharpness(rgb).enhance(factor)
            rgb.close()
            rgb = sharpened
        output = io.BytesIO()
        rgb.save(output, format="JPEG", quality=93, optimize=True, progressive=True)
        return output.getvalue(), (width, height), rgb.size
    finally:
        for picture in (rgb, cropped, rotated, canonical):
            if picture is not None:
                picture.close()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "LA", "P", "L", "CMYK"])
@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
@pytest.mark.parametrize("maximum", [None, 96])
def test_upload_bytes_and_metadata_match_existing_pipeline(mode: str, orientation: int,
                                                         maximum: int | None) -> None:
    content = _fixture(mode, orientation)
    result = UploadValidator(scanner=DisabledMalwareScanner()).validate(
        content=content, filename="fixture.jpg" if mode == "CMYK" else "fixture.png",
        declared_content_type="image/jpeg" if mode == "CMYK" else "image/png",
        max_dimension=maximum)
    assert result.content == _legacy_upload(content, maximum)
    with Image.open(io.BytesIO(result.content)) as picture:
        assert not picture.getexif()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "LA", "P", "L", "CMYK"])
@pytest.mark.parametrize("orientation", [1, 6, 8])
@pytest.mark.parametrize("rotation", [0, 45, 90])
@pytest.mark.parametrize(("sharpness", "version"), [(1, 1), (3, 1), (3, 2)])
@pytest.mark.parametrize("partial", [False, True])
def test_saved_crop_exact_bytes_and_dimensions_survive_buffer_reuse(
    mode: str, orientation: int, rotation: int, sharpness: float, version: int,
    partial: bool,
) -> None:
    content = _fixture(mode, orientation)
    x, y, width, height = (0.125, 0.125, 0.75, 0.75) if partial else (0, 0, 1, 1)
    expected, source_size, output_size = _legacy_crop(content, rotation, sharpness, version, partial)
    result = render_passport_image_crop(content, x=x, y=y, width=width, height=height,
                                       rotation_degrees=rotation, sharpness=sharpness,
                                       sharpness_algorithm_version=version)
    assert result.content == expected
    assert (result.source_width, result.source_height) == source_size
    assert (result.output_width, result.output_height) == output_size
    with Image.open(io.BytesIO(result.content)) as picture:
        assert not picture.getexif()
