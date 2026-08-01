"""Process-isolated, cumulatively bounded parsing for untrusted travel PDFs.

The API invokes this module from a worker thread.  PDF parsing happens only in
short-lived child processes, so a malformed parser input cannot indefinitely
hold an ASGI worker or retain unbounded parser state between requests.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import signal
import threading
import time
from collections.abc import Callable, Sequence
from multiprocessing.pool import AsyncResult
from typing import Any, TypeAlias, cast

PdfClassificationJob: TypeAlias = tuple[int, str, bytes, str]
PdfClassificationPayload: TypeAlias = dict[str, str | bool | None]

MAX_PDF_BATCH_PARSE_SECONDS = 20.0
MAX_PDF_BATCH_TEXT_CHARS = 12_000_000
MAX_PDF_PARSER_PROCESSES = 2
MAX_PDF_PARSER_TASKS_PER_CHILD = 250
PDF_PARSER_MEMORY_BYTES = 384 * 1024 * 1024
PDF_PARSER_ADMISSION_WAIT_SECONDS = 0.25
MAX_CONCURRENT_PDF_BATCHES = 2

_PDF_BATCH_ADMISSION = threading.BoundedSemaphore(MAX_CONCURRENT_PDF_BATCHES)


class _PdfFileTimeoutError(Exception):
    """Raised inside a parser child when one PDF exceeds its wall-time cap."""


def _timeout_one_pdf(_signum: int, _frame: object) -> None:
    raise _PdfFileTimeoutError


def _configure_parser_process(max_batch_seconds: float) -> None:
    """Apply defense-in-depth process limits where the OS supports them."""

    try:
        import resource

        setrlimit = getattr(resource, "setrlimit")
        setrlimit(
            getattr(resource, "RLIMIT_AS"),
            (PDF_PARSER_MEMORY_BYTES, PDF_PARSER_MEMORY_BYTES),
        )
        cpu_seconds = max(1, math.ceil(max_batch_seconds) + 2)
        setrlimit(getattr(resource, "RLIMIT_CPU"), (cpu_seconds, cpu_seconds))
    except (ImportError, OSError, ValueError):
        # Windows has no ``resource`` module.  The parent-enforced process
        # deadline remains authoritative on every platform.
        pass


def _failed_payload(filename: str, reason: str) -> PdfClassificationPayload:
    return {
        "original_filename": filename,
        "detected_type": "unknown",
        "accepted": False,
        "reason": reason,
        "text": "",
        "extracted_name": None,
        "extracted_passport_number": None,
        "extracted_reference": None,
    }


def _classify_one_pdf(
    job: PdfClassificationJob,
    per_file_seconds: float,
) -> tuple[int, PdfClassificationPayload]:
    """Classify one PDF inside a disposable parser process."""

    index, filename, content, expected_type = job
    alarm_signal = getattr(signal, "SIGALRM", None)
    interval_timer = getattr(signal, "ITIMER_REAL", None)
    set_interval_timer = getattr(signal, "setitimer", None)
    alarm_supported = (
        os.name != "nt"
        and alarm_signal is not None
        and interval_timer is not None
        and callable(set_interval_timer)
    )
    alarm_signal_number = int(alarm_signal) if alarm_signal is not None else 0
    interval_timer_number = int(interval_timer) if interval_timer is not None else 0
    set_timer = cast(Callable[[int, float], object], set_interval_timer)
    previous_handler: Any = None
    try:
        if alarm_supported:
            previous_handler = signal.signal(alarm_signal_number, _timeout_one_pdf)
            set_timer(interval_timer_number, per_file_seconds)

        # Import lazily so the spawned process never needs to pickle the matcher
        # (and so importing the main API process does not initialize pypdf here).
        from app.infrastructure.documents.document_matcher import DocumentMatcher

        classification = DocumentMatcher().classify(
            filename=filename,
            content=content,
            expected_type=expected_type,
        )
        if not isinstance(classification.text, str) or (
            len(classification.text) > MAX_PDF_BATCH_TEXT_CHARS
        ):
            # Never send a single over-budget extraction through the process
            # pipe.  The parent also enforces the cumulative batch budget.
            return index, _failed_payload(
                filename,
                "PDF request text budget was exhausted",
            )
        return index, {
            "original_filename": classification.original_filename,
            "detected_type": classification.detected_type,
            "accepted": classification.accepted,
            "reason": classification.reason,
            "text": classification.text,
            "extracted_name": classification.extracted_name,
            "extracted_passport_number": classification.extracted_passport_number,
            "extracted_reference": classification.extracted_reference,
        }
    except _PdfFileTimeoutError:
        return index, _failed_payload(filename, "PDF parsing exceeded the per-file safety limit")
    except BaseException:
        # Child exceptions are deliberately converted to a content-free,
        # fail-closed result.  Exception strings can contain attacker-controlled
        # PDF data and must not cross the process boundary or reach logs.
        return index, _failed_payload(filename, "PDF could not be parsed safely")
    finally:
        if alarm_supported:
            set_timer(interval_timer_number, 0)
            if previous_handler is not None:
                signal.signal(alarm_signal_number, previous_handler)


def classify_pdf_batch_isolated(
    jobs: Sequence[tuple[str, bytes, str]],
    *,
    batch_timeout_seconds: float = MAX_PDF_BATCH_PARSE_SECONDS,
    per_file_timeout_seconds: float = 3.0,
) -> list[PdfClassificationPayload]:
    """Classify a request batch with hard process and output budgets.

    Results preserve input order.  If the cumulative deadline, memory limit,
    worker startup, or result budget is exceeded, every unfinished item fails
    closed without attempting in-process parsing.
    """

    if not jobs:
        return []
    if batch_timeout_seconds <= 0 or per_file_timeout_seconds <= 0:
        return [
            _failed_payload(filename, "PDF request parsing budget was exhausted")
            for filename, _content, _expected_type in jobs
        ]

    admission_wait = min(PDF_PARSER_ADMISSION_WAIT_SECONDS, batch_timeout_seconds)
    if not _PDF_BATCH_ADMISSION.acquire(timeout=admission_wait):
        return [
            _failed_payload(filename, "PDF parser capacity is temporarily exhausted")
            for filename, _content, _expected_type in jobs
        ]
    try:
        try:
            return _classify_pdf_batch_admitted(
                jobs,
                batch_timeout_seconds=batch_timeout_seconds,
                per_file_timeout_seconds=per_file_timeout_seconds,
            )
        except Exception:
            return [
                _failed_payload(filename, "PDF parser service is temporarily unavailable")
                for filename, _content, _expected_type in jobs
            ]
    finally:
        _PDF_BATCH_ADMISSION.release()


def _classify_pdf_batch_admitted(
    jobs: Sequence[tuple[str, bytes, str]],
    *,
    batch_timeout_seconds: float,
    per_file_timeout_seconds: float,
) -> list[PdfClassificationPayload]:
    """Run one batch after the process-local admission slot is acquired."""

    indexed_jobs: list[PdfClassificationJob] = [
        (index, filename, content, expected_type)
        for index, (filename, content, expected_type) in enumerate(jobs)
    ]
    results: list[PdfClassificationPayload | None] = [None] * len(jobs)
    pending: dict[int, AsyncResult[tuple[int, PdfClassificationPayload]]] = {}
    deadline = time.monotonic() + batch_timeout_seconds
    total_text_chars = 0
    process_count = min(MAX_PDF_PARSER_PROCESSES, len(jobs))
    context = multiprocessing.get_context("spawn")
    pool = None

    try:
        pool = context.Pool(
            processes=process_count,
            initializer=_configure_parser_process,
            initargs=(batch_timeout_seconds,),
            maxtasksperchild=MAX_PDF_PARSER_TASKS_PER_CHILD,
        )
        active_pool = pool
        next_job_index = 0

        def submit_one() -> None:
            nonlocal next_job_index
            job = indexed_jobs[next_job_index]
            pending[job[0]] = active_pool.apply_async(
                _classify_one_pdf,
                (job, per_file_timeout_seconds),
            )
            next_job_index += 1

        # multiprocessing.Pool's result handler retains every completed
        # AsyncResult until the parent consumes it.  Keep only one task per
        # worker in flight so even a 1,500-file request cannot accumulate a
        # batch-sized text result for every file in parent memory.
        while next_job_index < len(indexed_jobs) and len(pending) < process_count:
            submit_one()
        if next_job_index == len(indexed_jobs):
            active_pool.close()

        while pending and time.monotonic() < deadline:
            made_progress = False
            for requested_index, async_result in tuple(pending.items()):
                if not async_result.ready():
                    continue
                made_progress = True
                try:
                    returned_index, payload = async_result.get(timeout=0)
                except Exception:
                    returned_index = requested_index
                    payload = _failed_payload(
                        jobs[requested_index][0],
                        "PDF parser process failed safely",
                    )
                if returned_index != requested_index:
                    payload = _failed_payload(
                        jobs[requested_index][0],
                        "PDF parser returned an invalid result",
                    )
                text = payload.get("text")
                total_text_chars += len(text) if isinstance(text, str) else 0
                if total_text_chars > MAX_PDF_BATCH_TEXT_CHARS:
                    payload = _failed_payload(
                        jobs[requested_index][0],
                        "PDF request text budget was exhausted",
                    )
                    results[requested_index] = payload
                    pending.pop(requested_index, None)
                    break
                results[requested_index] = payload
                pending.pop(requested_index, None)
                if next_job_index < len(indexed_jobs):
                    submit_one()
                    if next_job_index == len(indexed_jobs):
                        active_pool.close()

            if total_text_chars > MAX_PDF_BATCH_TEXT_CHARS:
                break
            if not made_progress:
                time.sleep(0.005)

        if pending:
            pool.terminate()
            pool.join()
            pending.clear()
        else:
            pool.join()
        pool = None
    except Exception:
        if pool is not None:
            pool.terminate()
            pool.join()
            pool = None
        raise
    finally:
        if pool is not None:
            pool.terminate()
            pool.join()

    final_results: list[PdfClassificationPayload] = []
    for index, result_payload in enumerate(results):
        final_results.append(
            result_payload
            if result_payload is not None
            else _failed_payload(
                jobs[index][0],
                "PDF request parsing budget was exhausted",
            )
        )
    return final_results
