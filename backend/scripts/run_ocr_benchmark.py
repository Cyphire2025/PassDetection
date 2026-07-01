"""Run an OCR benchmark manifest and emit a JSON report."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.infrastructure.ocr.benchmark import BenchmarkDataset, OCRBenchmarkRunner
from app.infrastructure.ocr.passport_extraction_service import PassportExtractionService


async def _run(manifest: Path, output: Path | None) -> None:
    dataset = BenchmarkDataset.load(manifest)
    report = await OCRBenchmarkRunner(PassportExtractionService()).run(dataset)
    payload = json.dumps(report.to_dict(), indent=2, sort_keys=True)
    if output is None:
        print(payload)
    else:
        output.write_text(payload + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PassDetection OCR benchmark suite")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    asyncio.run(_run(args.manifest, args.output))


if __name__ == "__main__":
    main()
