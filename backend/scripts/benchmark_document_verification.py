"""Synthetic, isolated PDF phase benchmark; never uses application data or messaging.

Run inside a resource-limited test container. The caller supplies separate
spawn/forkserver runs and a separate cloned ClamAV service for scan measurements.
The generated PDFs contain synthetic visa text only; timings do not establish
the throughput of real passenger documents.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import io
import json
import multiprocessing
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def fixtures(directory: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject

    directory.mkdir(parents=True, exist_ok=True)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, 42) if Path(font_path).exists() else ImageFont.load_default(size=42)
    for index in range(7):
        image = Image.new("RGB", (1240, 1754), "white")
        draw = ImageDraw.Draw(image)
        text = (
            "UNITED ARAB EMIRATES\nIMMIGRATION AUTHORITY\nE-VISA ENTRY PERMIT\n\n"
            f"Full name: SYNTHETIC TRAVELLER {index}\nPassport number: P123456{index}\n"
            f"Visa number: EV123456{index}\nNationality: INDIAN\n\n"
            "Valid from: 22 October 2026\nValid until: 25 November 2026\n"
            "Number of entries: SINGLE\n\nSYNTHETIC BENCHMARK DOCUMENT"
        )
        draw.multiline_text((75, 150), text, fill="black", font=font, spacing=25)
        rendered = io.BytesIO()
        image.save(rendered, format="PDF", resolution=120)
        image.close()
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(rendered.getvalue())))
        # Benign unreferenced stream makes scan payloads approximately one MiB;
        # this is not intended to simulate the compression of production visas.
        padding = DecodedStreamObject()
        padding.set_data(b"synthetic-fixture-padding-" * 40000)
        writer._add_object(padding)
        with (directory / f"synthetic-visa-{index}.pdf").open("wb") as output:
            writer.write(output)


def _jobs(directory: Path) -> list[tuple[str, bytes, str]]:
    return [(path.name, path.read_bytes(), "visa") for path in sorted(directory.glob("*.pdf"))]


def parser(directory: Path, method: str, runs: int) -> None:
    from app.infrastructure.documents import pdf_parser_sandbox as sandbox

    original_context = multiprocessing.get_context
    if method == "forkserver":
        multiprocessing.set_forkserver_preload(["app.infrastructure.documents.document_matcher"])
    # Prototype the context change without altering the application implementation.
    if method != "native":
        sandbox.multiprocessing.get_context = lambda _method: original_context(method)
    jobs = _jobs(directory)
    timings, signatures, accepted, reasons = [], [], [], []
    for _ in range(runs):
        start = time.monotonic()
        results = sandbox._classify_pdf_batch_admitted(jobs, batch_timeout_seconds=90, per_file_timeout_seconds=10)
        timings.append(round(time.monotonic() - start, 4))
        signatures.append(hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest())
        accepted.append(sum(bool(result["accepted"]) for result in results))
        reasons.append(sorted({str(result["reason"]) for result in results}))
    print(json.dumps({"phase": "parser", "method": method, "file_sizes": [len(job[1]) for job in jobs],
        "seconds": timings, "warm_median_seconds": statistics.median(timings[1:] or timings),
        "result_signatures": signatures, "accepted_counts": accepted, "reasons": reasons}), flush=True)


async def scans(directory: Path, host: str, concurrency: int, runs: int) -> None:
    from app.infrastructure.security.upload_security import _validate_pdf_structure
    from app.infrastructure.security.upload_validator import ClamAVMalwareScanner

    scanner = ClamAVMalwareScanner(host=host, port=3310, timeout_seconds=10)
    jobs = _jobs(directory)
    semaphore = asyncio.Semaphore(concurrency)

    async def check(content: bytes) -> None:
        async with semaphore:
            await asyncio.to_thread(scanner.scan, content)
            await asyncio.to_thread(_validate_pdf_structure, content)

    timings = []
    for _ in range(runs):
        start = time.monotonic()
        await asyncio.gather(*(check(content) for _name, content, _kind in jobs))
        timings.append(round(time.monotonic() - start, 4))
    print(json.dumps({"phase": "scan_and_structure", "concurrency": concurrency,
        "file_sizes": [len(job[1]) for job in jobs], "seconds": timings,
        "warm_median_seconds": statistics.median(timings[1:] or timings),
        "durable_audit_included": False}), flush=True)


async def compare_scans(directory: Path, host: str, runs: int) -> None:
    from app.infrastructure.security.upload_security import _validate_pdf_structure
    from app.infrastructure.security.upload_validator import ClamAVMalwareScanner

    scanner = ClamAVMalwareScanner(host=host, port=3310, timeout_seconds=10)
    jobs = _jobs(directory)
    timings: dict[int, list[float]] = {1: [], 2: []}
    for run in range(runs):
        # Alternate the order to avoid attributing scanner warm-up to concurrency.
        for concurrency in ((1, 2) if run % 2 == 0 else (2, 1)):
            semaphore = asyncio.Semaphore(concurrency)

            async def check(content: bytes) -> None:
                async with semaphore:
                    await asyncio.to_thread(scanner.scan, content)
                    await asyncio.to_thread(_validate_pdf_structure, content)

            start = time.monotonic()
            await asyncio.gather(*(
                check(content + f"\n% synthetic run {run} concurrency {concurrency}\n".encode())
                for _name, content, _kind in jobs
            ))
            timings[concurrency].append(round(time.monotonic() - start, 4))
    print(json.dumps({"phase": "scan_compare", "file_sizes": [len(job[1]) for job in jobs],
        "seconds": timings, "warm_median_seconds": {
            key: statistics.median(values[1:] or values) for key, values in timings.items()},
        "all_scans_and_structure_checks_passed": True, "durable_audit_included": False}), flush=True)


_probe_state: list[str] = []


def _probe_child_identity(job, _per_file_seconds):
    from app.infrastructure.documents import pdf_parser_sandbox as sandbox

    _probe_state.append(job[1])
    result = sandbox._failed_payload(job[1], "synthetic child identity probe")
    result["child_pid"] = str(os.getpid())
    result["state"] = ",".join(_probe_state)
    return job[0], result


def _probe_child_memory(job, _per_file_seconds):
    import resource

    from app.infrastructure.documents import pdf_parser_sandbox as sandbox

    assert resource.getrlimit(resource.RLIMIT_AS) == (sandbox.PDF_PARSER_MEMORY_BYTES,) * 2
    try:
        bytearray(512 * 1024 * 1024)
    except MemoryError:
        return job[0], sandbox._failed_payload(job[1], "memory limit enforced")
    raise AssertionError("Parser child allocation exceeded its memory limit")


def _probe_hung_child(job, _per_file_seconds):
    time.sleep(30)
    raise AssertionError("Parent failed to terminate the hung parser")


def _probe_file_alarm(job, per_file_seconds):
    from app.infrastructure.documents import pdf_parser_sandbox as sandbox
    from app.infrastructure.documents.document_matcher import DocumentMatcher

    def synthetic_slow_classify(self, **kwargs):
        time.sleep(30)

    DocumentMatcher.classify = synthetic_slow_classify
    return sandbox._classify_one_pdf(job, per_file_seconds)


def safety_probes(directory: Path) -> None:
    from app.infrastructure.documents import pdf_parser_sandbox as sandbox

    original = sandbox._classify_one_pdf
    jobs = _jobs(directory)

    def run(probe, filename, *, deadline=5, file_seconds=0.2):
        sandbox._classify_one_pdf = probe
        try:
            return sandbox._classify_pdf_batch_admitted(
                [(filename, jobs[0][1], "visa")],
                batch_timeout_seconds=deadline,
                per_file_timeout_seconds=file_seconds,
            )[0]
        finally:
            sandbox._classify_one_pdf = original

    first = run(_probe_child_identity, "first.pdf")
    second = run(_probe_child_identity, "second.pdf")
    assert first["child_pid"] != second["child_pid"]
    assert first["state"] == "first.pdf" and second["state"] == "second.pdf"
    assert not Path(f"/proc/{first['child_pid']}").exists()
    assert not Path(f"/proc/{second['child_pid']}").exists()
    memory = run(_probe_child_memory, "memory.pdf")
    assert memory["reason"] == "memory limit enforced"
    alarm = run(_probe_file_alarm, "alarm.pdf")
    assert alarm["reason"] == "PDF parsing exceeded the per-file safety limit"
    start = time.monotonic()
    hung = run(_probe_hung_child, "hung.pdf", deadline=0.25)
    elapsed = time.monotonic() - start
    assert elapsed < 3 and hung["reason"] == "PDF request parsing budget was exhausted"
    invalid = sandbox._classify_pdf_batch_admitted(
        [("bad.pdf", b"%PDF-1.7\ntruncated", "visa"), ("bad.txt", b"not PDF", "visa")],
        batch_timeout_seconds=10, per_file_timeout_seconds=1,
    )
    assert [item["original_filename"] for item in invalid] == ["bad.pdf", "bad.txt"]
    assert all(item["accepted"] is False for item in invalid)
    assert not multiprocessing.active_children()
    print(json.dumps({"phase": "safety_probes", "fresh_children_no_retained_state": True,
        "memory_limit_bytes": sandbox.PDF_PARSER_MEMORY_BYTES, "memory_allocation_rejected": True,
        "per_file_alarm_enforced": True, "parent_timeout_seconds": round(elapsed, 4),
        "bad_pdfs_fail_closed_in_order": True, "no_active_parser_children": True}), flush=True)


def idle_parent(directory: Path, method: str) -> None:
    from app.infrastructure.documents import (
        document_matcher,  # noqa: F401 -- API imports this before parsing
    )
    from app.infrastructure.documents import pdf_parser_sandbox as sandbox

    original_context = multiprocessing.get_context
    if method == "forkserver":
        multiprocessing.set_forkserver_preload(["app.infrastructure.documents.document_matcher"])
    if method != "native":
        sandbox.multiprocessing.get_context = lambda _method: original_context(method)
    print(json.dumps({"ready": True}), flush=True)
    for command in sys.stdin:
        if command.strip() == "stop":
            return
        assert command.strip() == "run"
        jobs = _jobs(directory)
        timings, signatures, counts = [], [], []
        for _ in range(2):
            start = time.monotonic()
            results = sandbox._classify_pdf_batch_admitted(jobs, batch_timeout_seconds=90, per_file_timeout_seconds=10)
            timings.append(round(time.monotonic() - start, 4))
            signatures.append(hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest())
            counts.append(sum(bool(result["accepted"]) for result in results))
        del jobs, results
        gc.collect()
        print(json.dumps({"seconds": timings, "signatures": signatures, "accepted": counts,
            "active_parser_children": len(multiprocessing.active_children())}), flush=True)


def idle_comparison(directory: Path, method: str) -> None:
    parents = []
    memory_file = Path("/sys/fs/cgroup/memory.current")
    try:
        for _ in range(4):
            process = subprocess.Popen([sys.executable, __file__, "idle_parent", "--fixtures", str(directory), "--method", method],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            parents.append(process)
            assert json.loads(process.stdout.readline())["ready"]
        time.sleep(2)
        before = int(memory_file.read_text())
        results, retained_bytes = [], []
        for process in parents:
            process.stdin.write("run\n")
            process.stdin.flush()
            results.append(json.loads(process.stdout.readline()))
            time.sleep(1)
            retained_bytes.append(int(memory_file.read_text()))
        # Keep all four independent parent interpreters alive while measuring.
        time.sleep(5)
        after = int(memory_file.read_text())
        print(json.dumps({"phase": "four_parent_idle", "method": method,
            "initial_idle_memory_bytes": before, "after_each_parent_memory_bytes": retained_bytes,
            "final_idle_memory_bytes": after, "per_parent_results": results,
            "parent_scope": "parser and matcher imports; full API application excluded"}), flush=True)
    finally:
        for process in parents:
            if process.poll() is None:
                process.stdin.write("stop\n")
                process.stdin.flush()
        for process in parents:
            process.wait(timeout=10)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("phase", choices=["generate", "parser", "scan", "scan_compare", "safety", "idle_parent", "idle_compare"])
    cli.add_argument("--fixtures", type=Path, default=Path("/bench/fixtures"))
    cli.add_argument("--method", choices=["spawn", "forkserver", "native"], default="spawn")
    cli.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
    cli.add_argument("--runs", type=int, default=4)
    cli.add_argument("--scanner-host", default="scan")
    args = cli.parse_args()
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    if args.phase == "generate":
        fixtures(args.fixtures)
        print(json.dumps({"generated": len(_jobs(args.fixtures))}), flush=True)
    elif args.phase == "parser":
        parser(args.fixtures, args.method, args.runs)
    elif args.phase == "scan_compare":
        asyncio.run(compare_scans(args.fixtures, args.scanner_host, args.runs))
    elif args.phase == "safety":
        safety_probes(args.fixtures)
    elif args.phase == "idle_parent":
        idle_parent(args.fixtures, args.method)
    elif args.phase == "idle_compare":
        idle_comparison(args.fixtures, args.method)
    else:
        asyncio.run(scans(args.fixtures, args.scanner_host, args.concurrency, args.runs))
