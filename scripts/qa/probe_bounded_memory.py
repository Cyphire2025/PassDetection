"""Synthetic parser/worker memory measurements inside an isolated runtime image.

This is a resource probe, not an ingestion security or provider qualification.
The runner supplies --network=none and read-only generated fixtures. No real
storage, database, credential, malware decision or provider call is involved.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import gc
import hashlib
import io
import json
import multiprocessing
import os
import resource
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "/app")


def measure() -> dict:
    cgroup = Path("/sys/fs/cgroup")
    return {
        "cgroup_peak_bytes": int((cgroup / "memory.peak").read_text()),
        "cgroup_current_bytes": int((cgroup / "memory.current").read_text()),
        "cgroup_events": dict(line.split() for line in (cgroup / "memory.events").read_text().splitlines()),
        "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def generate(directory: Path) -> None:
    from PIL import Image, ImageDraw
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject

    directory.mkdir(parents=True, exist_ok=True)
    for kind, mode, size in (("passport-rgb", "RGB", (6000, 4000)),
                             ("passport-rgba", "RGBA", (6000, 4000)),
                             ("ecr-rgba", "RGBA", (8000, 5000))):
        with Image.new(mode, size, (220, 230, 240, 125) if mode == "RGBA" else (220, 230, 240)) as picture:
            draw = ImageDraw.Draw(picture)
            for y in range(0, size[1], 40):
                draw.line((0, y, size[0], y), fill="black", width=2)
            picture.save(directory / f"{kind}.png")
    writer = PdfWriter()
    for _ in range(100):
        writer.add_blank_page(width=612, height=792)
    # A valid 100-page PDF close to the accepted 25 MiB ceiling. The unused
    # stream is deliberately stored without compression; no compressed-bomb shortcut.
    stream = DecodedStreamObject()
    stream.set_data(bytes(range(256)) * (24 * 1024 * 1024 // 256))
    writer._root_object[NameObject("/QualificationPayload")] = writer._add_object(stream)
    with (directory / "email-100-pages.pdf").open("wb") as output:
        writer.write(output)
    assert 24 * 1024 * 1024 < (directory / "email-100-pages.pdf").stat().st_size < 25 * 1024 * 1024
    manifest = {}
    for path in sorted(directory.iterdir()):
        if path.is_file():
            content = path.read_bytes()
            manifest[path.name] = {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2))


class FixtureDigestScanner:
    """Admit only the fixture bytes; this probe does not claim malware coverage."""

    def __init__(self, value: bytes) -> None:
        self.expected = hashlib.sha256(value).digest()

    def scan(self, value: bytes) -> None:
        assert hashlib.sha256(value).digest() == self.expected


def execute(mode: str, directory: Path) -> dict:
    from app.core.config.settings import get_settings
    from PIL import Image

    settings = get_settings()
    if mode == "baseline":
        time.sleep(0.2)
        return {"operation": "loaded worker child"}
    if mode in {"passport-rgb", "passport-rgba"}:
        from app.infrastructure.security.upload_validator import UploadValidator
        content = (directory / f"{mode}.png").read_bytes()
        validator = UploadValidator(scanner=FixtureDigestScanner(content))
        result = validator.validate(content=content, filename="synthetic.png", declared_content_type="image/png")
        with Image.open(io.BytesIO(result.content)) as image:
            assert image.size == (6000, 4000)
        return {"accepted_pixels": 24_000_000, "result_bytes": len(result.content)}
    if mode == "extraction":
        from app.infrastructure.ocr.preprocessing.image_preprocessor import (
            OCRImagePreprocessor,
        )
        content = (directory / "passport-rgb.png").read_bytes()
        processor = OCRImagePreprocessor()
        normalized = processor.normalize(content)
        processor.assess_quality(normalized)
        jobs = processor.tesseract_jobs(normalized)
        assert jobs
        for picture, _ in jobs:
            picture.close()
        return {"source_pixels": 24_000_000, "normalized_bytes": len(normalized), "ocr_variants": len(jobs)}
    if mode == "extraction-full":
        from app.infrastructure.ocr.passport_extraction_service import (
            PassportExtractionService,
        )
        content = (directory / "passport-rgb.png").read_bytes()
        result = asyncio.run(PassportExtractionService().extract(content, filename="synthetic.png", content_type="image/png"))
        return {"source_pixels": 24_000_000, "field_count": len(result.extracted_fields),
                "local_timeout_seconds": 10, "external_provider_calls": False}
    if mode in {"ecr", "ecr-single"}:
        from app.infrastructure.ai.gemini_ecr_service import prepare_ecr_image
        content = (directory / "ecr-rgba.png").read_bytes()
        threads = 1 if mode == "ecr-single" else 2
        with ThreadPoolExecutor(max_workers=threads) as executor:
            results = list(executor.map(lambda _: prepare_ecr_image(content, settings=settings), range(threads)))
        assert len(results) == threads
        return {"source_pixels_each": 40_000_000, "simultaneous_decoder_threads": threads}
    if mode == "email":
        from app.infrastructure.email.gmail_provider import _decode_attachment
        from app.infrastructure.email.pdf_validator import EmailPdfValidator
        content = (directory / "email-100-pages.pdf").read_bytes()
        encoded = base64.urlsafe_b64encode(content).decode("ascii")
        decoded = _decode_attachment(encoded, max_bytes=settings.email_attachment_max_bytes)
        result = EmailPdfValidator(settings=settings, scanner=FixtureDigestScanner(content)).validate(
            content=decoded, filename="synthetic.pdf", declared_content_type="application/pdf")
        assert result.page_count == 100 and result.content == content
        return {"accepted_pages": 100, "accepted_bytes": len(content)}
    if mode in {"gemini-extraction", "gemini-verification"}:
        # Exercise actual request serialization while retaining the source bytes.
        # This bounds the configured upload byte ceiling; it does not contact AI.
        import httpx
        content = bytes(range(256)) * (settings.upload_max_file_size_bytes // 256)
        if mode == "gemini-extraction":
            from app.infrastructure.ai.gemini_passport_verification_service import (
                GeminiPassportVerificationService,
            )
            payload = GeminiPassportVerificationService()._request_payload(content, "image/jpeg", {})
        else:
            from app.infrastructure.ai.gemini_post_submission_verification_service import (
                GeminiPostSubmissionVerificationService,
            )
            payload = GeminiPostSubmissionVerificationService()._request_payload(content, content_type="image/jpeg", submitted_fields={})
        request = httpx.Request("POST", "https://synthetic.invalid/never-sent", json=payload)
        assert len(request.content) > len(content)
        return {"retained_source_bytes": len(content), "http_request_bytes": len(request.content), "provider_calls": 0}
    if mode == "visa-image":
        from app.infrastructure.ai.gemini_visa_image_edit_service import (
            GeminiVisaImageEditService,
        )
        content = (directory / "passport-rgb.png").read_bytes()
        result = GeminiVisaImageEditService._canonical_image(content)
        with Image.open(io.BytesIO(result)) as image:
            assert image.size == (6000, 4000)
        return {"accepted_pixels": 24_000_000, "result_bytes": len(result)}
    if mode == "crop":
        from app.infrastructure.imaging.passport_image_cropper import (
            render_passport_image_crop,
        )
        content = (directory / "passport-rgb.png").read_bytes()
        result = render_passport_image_crop(content, x=0, y=0, width=1, height=1,
                                           rotation_degrees=45, sharpness=3)
        return {"source_pixels": 24_000_000, "output_pixels": result.output_width * result.output_height,
                "result_bytes": len(result.content)}
    raise ValueError("Unsupported probe mode")


def child(mode: str, directory: Path, writer, repetitions: int) -> None:
    try:
        samples = []
        for _ in range(repetitions):
            result = execute(mode, directory)
            samples.append(measure())
        writer.send({"status": "passed", "operation": result, "repetitions": repetitions,
                     "retained_process_samples": samples, **measure()})
    except BaseException as error:
        writer.send({"status": "failed", "error_type": type(error).__name__, "message": str(error), **measure()})
        raise
    finally:
        writer.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["generate", "baseline", "passport-rgb", "passport-rgba", "extraction", "extraction-full", "ecr", "ecr-single", "email", "visa-image", "crop", "gemini-extraction", "gemini-verification"])
    parser.add_argument("--fixtures", type=Path, default=Path("/fixtures"))
    parser.add_argument("--children", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--repetitions", type=int, choices=range(1, 21), default=1)
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.fixtures)
        return
    assert os.environ.get("APP_ENV") == "development" and os.environ.get("POSTGRES_DB") == "passdetection_ci_memory"
    from app.infrastructure.processing.celery_app import celery_app
    celery_app.loader.import_default_modules()
    gc.collect()
    baseline = measure()
    context = multiprocessing.get_context("fork")
    processes = []
    readers = []
    for _ in range(args.children):
        reader, writer = context.Pipe(duplex=False)
        process = context.Process(target=child, args=(args.mode, args.fixtures, writer, args.repetitions))
        process.start()
        writer.close()
        processes.append(process)
        readers.append(reader)
    for process in processes:
        process.join(timeout=120)
        if process.is_alive():
            process.terminate()
            process.join()
            raise RuntimeError("Synthetic bounded workload exceeded two minutes")
    results = [reader.recv() if reader.poll(1) else {"status": "missing"} for reader in readers]
    result = {"mode": args.mode, "children": args.children, "baseline": baseline,
              "results": results, "exit_codes": [process.exitcode for process in processes], **measure()}
    print(json.dumps(result))
    if any(process.exitcode != 0 for process in processes) or any(item["status"] != "passed" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
