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
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from multiprocessing.pool import AsyncResult
from typing import Any, TypeAlias, cast

from redis import Redis

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger

PdfClassificationJob: TypeAlias = tuple[int, str, bytes, str]
PdfClassificationPayload: TypeAlias = dict[str, str | bool | None]

MAX_PDF_BATCH_PARSE_SECONDS = 20.0
MAX_PDF_FILE_PARSE_SECONDS = 10.0
MAX_PDF_SCALED_BATCH_SECONDS = 90.0
MAX_PDF_BATCH_TEXT_CHARS = 12_000_000
MAX_PDF_PARSER_PROCESSES = 2
MAX_PDF_PARSER_TASKS_PER_CHILD = 250
PDF_PARSER_MEMORY_BYTES = 384 * 1024 * 1024
PDF_PARSER_ADMISSION_WAIT_SECONDS = 0.25
MAX_PROCESS_LOCAL_PDF_BATCHES = 1
MAX_DEPLOYMENT_PDF_BATCHES = 2
PDF_BATCH_LEASE_KEY = "global-connect:pdf-parser:batch-leases:v1"
PDF_BATCH_LEASE_GRACE_MS = 15_000
PDF_BATCH_LEASE_MIN_MS = 30_000
PDF_BATCH_LEASE_MAX_MS = 120_000

_PDF_BATCH_ADMISSION = threading.BoundedSemaphore(MAX_PROCESS_LOCAL_PDF_BATCHES)
logger = get_logger(__name__)

_ACQUIRE_PDF_BATCH_LEASE_LUA = """
local redis_time = redis.call('TIME')
local now_ms = (tonumber(redis_time[1]) * 1000) + math.floor(tonumber(redis_time[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[2]) then
  return 0
end
local expires_at_ms = now_ms + tonumber(ARGV[3])
redis.call('ZADD', KEYS[1], expires_at_ms, ARGV[1])
local latest = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
if latest[2] then
  redis.call('PEXPIREAT', KEYS[1], math.floor(tonumber(latest[2])) + 1000)
end
return 1
"""

_RELEASE_PDF_BATCH_LEASE_LUA = """
local removed = redis.call('ZREM', KEYS[1], ARGV[1])
local latest = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
if latest[2] then
  redis.call('PEXPIREAT', KEYS[1], math.floor(tonumber(latest[2])) + 1000)
else
  redis.call('DEL', KEYS[1])
end
return removed
"""


class _PdfBatchLeaseUnavailable(RuntimeError):
    """The production-wide parser admission store could not be reached safely."""


@dataclass(slots=True)
class _PdfBatchLease:
    client: Any
    token: str
    released: bool = False

    def release(self) -> None:
        """Release this exact lease once; expiry remains the crash fallback."""

        if self.released:
            return
        self.released = True
        try:
            self.client.eval(
                _RELEASE_PDF_BATCH_LEASE_LUA,
                1,
                PDF_BATCH_LEASE_KEY,
                self.token,
            )
        except Exception:
            # Never expose the random lease member or Redis connection details.
            # The sorted-set score and key expiry reclaim the slot after a crash
            # or a coordination-store outage.
            logger.warning("pdf_parser_global_lease_release_failed")


@lru_cache(maxsize=1)
def _pdf_batch_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(
        settings.redis.url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
        retry_on_timeout=False,
        decode_responses=False,
    )


def _production_global_pdf_batch_lease_required() -> bool:
    return get_settings().app_env == "production"


def _pdf_batch_lease_ms(batch_timeout_seconds: float) -> int:
    requested_ms = math.ceil(batch_timeout_seconds * 1000) + PDF_BATCH_LEASE_GRACE_MS
    return min(
        PDF_BATCH_LEASE_MAX_MS,
        max(PDF_BATCH_LEASE_MIN_MS, requested_ms),
    )


def _acquire_global_pdf_batch_lease(
    *,
    batch_timeout_seconds: float,
) -> _PdfBatchLease | None:
    """Atomically prune expired leases and acquire one deployment-wide slot."""

    token = uuid.uuid4().hex
    try:
        client = cast(Any, _pdf_batch_redis_client())
        result = client.eval(
            _ACQUIRE_PDF_BATCH_LEASE_LUA,
            1,
            PDF_BATCH_LEASE_KEY,
            token,
            str(MAX_DEPLOYMENT_PDF_BATCHES),
            str(_pdf_batch_lease_ms(batch_timeout_seconds)),
        )
        admitted = int(cast(Any, result))
    except Exception as exc:
        raise _PdfBatchLeaseUnavailable from exc
    if admitted == 0:
        return None
    if admitted != 1:
        raise _PdfBatchLeaseUnavailable
    return _PdfBatchLease(client=client, token=token)


def bounded_pdf_batch_timeout_seconds(job_count: int) -> float:
    """Budget all bounded workers without crossing the request timeout envelope."""

    waves = math.ceil(max(1, job_count) / MAX_PDF_PARSER_PROCESSES)
    worst_case_seconds = waves * MAX_PDF_FILE_PARSE_SECONDS + 5.0
    return min(
        MAX_PDF_SCALED_BATCH_SECONDS,
        max(MAX_PDF_BATCH_PARSE_SECONDS, worst_case_seconds),
    )


class _PdfFileTimeoutError(Exception):
    """Raised inside a parser child when one PDF exceeds its wall-time cap."""


def _timeout_one_pdf(_signum: int, _frame: object) -> None:
    raise _PdfFileTimeoutError


def _configure_parser_process(max_batch_seconds: float) -> None:
    """Apply defense-in-depth process limits where the OS supports them."""

    # Tesseract may otherwise create multiple OpenMP threads inside each of the
    # two isolated parser processes. Keeping one OCR thread per child avoids CPU
    # oversubscription and makes bulk latency predictable under load.
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
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
        from app.infrastructure.documents.document_matcher import (
            PDF_OCR_RETRY_REASON,
            DocumentMatcher,
            DocumentOcrUnavailableError,
        )

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
    except DocumentOcrUnavailableError:
        return index, _failed_payload(filename, PDF_OCR_RETRY_REASON)
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
    per_file_timeout_seconds: float = MAX_PDF_FILE_PARSE_SECONDS,
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

    effective_batch_timeout_seconds = min(
        batch_timeout_seconds,
        MAX_PDF_SCALED_BATCH_SECONDS,
    )
    admission_wait = min(PDF_PARSER_ADMISSION_WAIT_SECONDS, effective_batch_timeout_seconds)
    if not _PDF_BATCH_ADMISSION.acquire(timeout=admission_wait):
        return [
            _failed_payload(filename, "PDF parser capacity is temporarily exhausted")
            for filename, _content, _expected_type in jobs
        ]
    global_lease: _PdfBatchLease | None = None
    try:
        if _production_global_pdf_batch_lease_required():
            try:
                global_lease = _acquire_global_pdf_batch_lease(
                    batch_timeout_seconds=effective_batch_timeout_seconds,
                )
            except _PdfBatchLeaseUnavailable:
                return [
                    _failed_payload(filename, "PDF parser service is temporarily unavailable")
                    for filename, _content, _expected_type in jobs
                ]
            if global_lease is None:
                return [
                    _failed_payload(filename, "PDF parser capacity is temporarily exhausted")
                    for filename, _content, _expected_type in jobs
                ]
        try:
            return _classify_pdf_batch_admitted(
                jobs,
                batch_timeout_seconds=effective_batch_timeout_seconds,
                per_file_timeout_seconds=per_file_timeout_seconds,
            )
        except Exception:
            return [
                _failed_payload(filename, "PDF parser service is temporarily unavailable")
                for filename, _content, _expected_type in jobs
            ]
    finally:
        try:
            if global_lease is not None:
                global_lease.release()
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
