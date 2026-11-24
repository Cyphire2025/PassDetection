from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.email import sync_attachments
from app.infrastructure.email.pdf_validator import ValidatedEmailPdf


def _request_arguments():
    return {
        "content": b"synthetic-provider-content",
        "filename": "ticket.pdf",
        "declared_content_type": "application/pdf",
        "settings": SimpleNamespace(email_attachment_max_bytes=1024),
        "agency_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "security_service": SimpleNamespace(validate_document=AsyncMock(return_value="a" * 64)),
    }


def _validated():
    return ValidatedEmailPdf(
        b"synthetic-provider-content", "ticket.pdf", "application/pdf", "a" * 64, 1
    )


async def test_email_pdf_parsing_runs_outside_the_event_loop(monkeypatch):
    loop_thread = threading.get_ident()
    parser_threads = []
    result = _validated()

    def parse(**_arguments):
        parser_threads.append(threading.get_ident())
        return result

    monkeypatch.setattr(
        sync_attachments, "EmailPdfValidator", lambda **_: SimpleNamespace(validate=parse)
    )
    assert await sync_attachments._validate_untrusted_email_pdf(**_request_arguments()) is result
    assert len(parser_threads) == 1
    assert parser_threads[0] != loop_thread


async def test_cancellation_waits_until_claimed_pdf_work_finishes(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def parse(**_arguments):
        started.set()
        if not release.wait(timeout=10):
            raise TimeoutError("Synthetic PDF work was not released")
        finished.set()
        return _validated()

    monkeypatch.setattr(
        sync_attachments, "EmailPdfValidator", lambda **_: SimpleNamespace(validate=parse)
    )
    task = asyncio.create_task(
        sync_attachments._validate_untrusted_email_pdf(**_request_arguments())
    )
    try:
        assert await asyncio.to_thread(started.wait, 10)
        task.cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
