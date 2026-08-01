from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfWriter

from app.infrastructure.documents import pdf_parser_sandbox
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    classify_documents_bounded,
)


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_windows_spawn_path_returns_ordered_fail_closed_results() -> None:
    jobs = [
        ("first.txt", b"not a PDF", "visa"),
        ("second.pdf", _blank_pdf(), "flight_ticket"),
    ]

    results = pdf_parser_sandbox.classify_pdf_batch_isolated(
        jobs,
        batch_timeout_seconds=10,
    )

    assert [result["original_filename"] for result in results] == [
        "first.txt",
        "second.pdf",
    ]
    assert all(result["accepted"] is False for result in results)
    assert all(result["text"] == "" for result in results)


class _FakeAdmission:
    def __init__(self, *, admitted: bool) -> None:
        self.admitted = admitted
        self.acquire_calls = 0
        self.release_calls = 0

    def acquire(self, *, timeout: float) -> bool:
        assert timeout >= 0
        self.acquire_calls += 1
        return self.admitted

    def release(self) -> None:
        self.release_calls += 1


def test_parser_admission_saturation_fails_closed_without_spawning(monkeypatch) -> None:
    admission = _FakeAdmission(admitted=False)
    monkeypatch.setattr(pdf_parser_sandbox, "_PDF_BATCH_ADMISSION", admission)
    context = SimpleNamespace(Pool=lambda **_kwargs: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(
        pdf_parser_sandbox.multiprocessing,
        "get_context",
        lambda _method: context,
    )

    results = pdf_parser_sandbox.classify_pdf_batch_isolated([("visa.pdf", _blank_pdf(), "visa")])

    assert results[0]["accepted"] is False
    assert "capacity" in str(results[0]["reason"])
    assert admission.acquire_calls == 1
    assert admission.release_calls == 0


def test_parser_admission_is_released_when_internal_runner_fails(monkeypatch) -> None:
    admission = _FakeAdmission(admitted=True)
    monkeypatch.setattr(pdf_parser_sandbox, "_PDF_BATCH_ADMISSION", admission)
    monkeypatch.setattr(
        pdf_parser_sandbox,
        "_classify_pdf_batch_admitted",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    results = pdf_parser_sandbox.classify_pdf_batch_isolated([("visa.pdf", _blank_pdf(), "visa")])

    assert results[0]["accepted"] is False
    assert "temporarily unavailable" in str(results[0]["reason"])
    assert admission.release_calls == 1


def test_pool_creation_failure_is_truthfully_retryable(monkeypatch) -> None:
    monkeypatch.setattr(
        pdf_parser_sandbox.multiprocessing,
        "get_context",
        lambda _method: SimpleNamespace(
            Pool=lambda **_kwargs: (_ for _ in ()).throw(OSError("unavailable"))
        ),
    )

    results = pdf_parser_sandbox.classify_pdf_batch_isolated([("visa.pdf", _blank_pdf(), "visa")])

    assert results[0]["accepted"] is False
    assert results[0]["reason"] == "PDF parser service is temporarily unavailable"


class _NeverReadyResult:
    def ready(self) -> bool:
        return False


class _ReadyResult:
    def __init__(self, value) -> None:
        self.value = value

    def ready(self) -> bool:
        return True

    def get(self, *, timeout: float):
        assert timeout == 0
        return self.value


class _FakePool:
    def __init__(self, result_factory) -> None:
        self._result_factory = result_factory
        self.submitted_indices: list[int] = []
        self.terminated = False
        self.joined = False
        self.closed = False

    def apply_async(self, _func, args):
        self.submitted_indices.append(args[0][0])
        return self._result_factory(args)

    def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        self.terminated = True

    def join(self) -> None:
        self.joined = True


def _install_fake_pool(monkeypatch, pool: _FakePool) -> None:
    monkeypatch.setattr(
        pdf_parser_sandbox.multiprocessing,
        "get_context",
        lambda method: SimpleNamespace(Pool=lambda **_kwargs: pool if method == "spawn" else None),
    )


def test_hard_cumulative_timeout_terminates_unfinished_pool(monkeypatch) -> None:
    pool = _FakePool(lambda _args: _NeverReadyResult())
    _install_fake_pool(monkeypatch, pool)

    results = pdf_parser_sandbox.classify_pdf_batch_isolated(
        [("hung.pdf", _blank_pdf(), "visa")],
        batch_timeout_seconds=0.01,
    )

    assert pool.closed is True
    assert pool.terminated is True
    assert pool.joined is True
    assert results[0]["accepted"] is False
    assert "budget" in str(results[0]["reason"])


def test_submission_window_is_bounded_to_worker_count(monkeypatch) -> None:
    pool = _FakePool(lambda _args: _NeverReadyResult())
    _install_fake_pool(monkeypatch, pool)

    results = pdf_parser_sandbox.classify_pdf_batch_isolated(
        [(f"{index}.pdf", _blank_pdf(), "visa") for index in range(20)],
        batch_timeout_seconds=0.01,
    )

    assert pool.submitted_indices == [0, 1]
    assert pool.terminated is True
    assert len(results) == 20
    assert all(result["accepted"] is False for result in results)


def test_output_budget_terminates_remaining_work(monkeypatch) -> None:
    monkeypatch.setattr(pdf_parser_sandbox, "MAX_PDF_BATCH_TEXT_CHARS", 3)

    def result_factory(args):
        job = args[0]
        index, filename, _content, _expected_type = job
        return _ReadyResult(
            (
                index,
                {
                    "original_filename": filename,
                    "detected_type": "visa",
                    "accepted": True,
                    "reason": "Accepted",
                    "text": "four",
                    "extracted_name": None,
                    "extracted_passport_number": None,
                    "extracted_reference": None,
                },
            )
        )

    pool = _FakePool(result_factory)
    _install_fake_pool(monkeypatch, pool)
    results = pdf_parser_sandbox.classify_pdf_batch_isolated(
        [
            ("first.pdf", _blank_pdf(), "visa"),
            ("second.pdf", _blank_pdf(), "visa"),
            ("third.pdf", _blank_pdf(), "visa"),
        ]
    )

    assert pool.terminated is True
    assert pool.submitted_indices == [0, 1]
    assert all(result["accepted"] is False for result in results)
    assert "text budget" in str(results[0]["reason"])
    assert "request parsing budget" in str(results[1]["reason"])
    assert "request parsing budget" in str(results[2]["reason"])


def test_budget_exhaustion_stops_rolling_replenishment(monkeypatch) -> None:
    monkeypatch.setattr(pdf_parser_sandbox, "MAX_PDF_BATCH_TEXT_CHARS", 5)

    def result_factory(args):
        job = args[0]
        index, filename, _content, _expected_type = job
        text = "ok" if index == 0 else "four"
        return _ReadyResult(
            (
                index,
                {
                    "original_filename": filename,
                    "detected_type": "visa",
                    "accepted": True,
                    "reason": "Accepted",
                    "text": text,
                    "extracted_name": None,
                    "extracted_passport_number": None,
                    "extracted_reference": None,
                },
            )
        )

    pool = _FakePool(result_factory)
    _install_fake_pool(monkeypatch, pool)

    results = pdf_parser_sandbox.classify_pdf_batch_isolated(
        [(f"{index}.pdf", _blank_pdf(), "visa") for index in range(5)]
    )

    # Job 2 replenishes the slot released by job 0.  Job 1 then exhausts
    # the budget, and no further work is allowed into the result window.
    assert pool.submitted_indices == [0, 1, 2]
    assert results[0]["accepted"] is True
    assert "text budget" in str(results[1]["reason"])
    assert all(results[index]["accepted"] is False for index in range(1, 5))


def test_child_rejects_single_over_budget_text_before_ipc(monkeypatch) -> None:
    monkeypatch.setattr(pdf_parser_sandbox, "MAX_PDF_BATCH_TEXT_CHARS", 3)
    classification = SimpleNamespace(
        original_filename="large.pdf",
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text="four",
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference=None,
    )
    monkeypatch.setattr(
        "app.infrastructure.documents.document_matcher.DocumentMatcher",
        lambda: SimpleNamespace(classify=lambda **_kwargs: classification),
    )

    returned_index, payload = pdf_parser_sandbox._classify_one_pdf(
        (0, "large.pdf", _blank_pdf(), "visa"),
        1,
    )

    assert returned_index == 0
    assert payload["accepted"] is False
    assert payload["text"] == ""
    assert payload["reason"] == "PDF request text budget was exhausted"


def test_invalid_child_payload_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        pdf_parser_sandbox,
        "classify_pdf_batch_isolated",
        lambda _jobs: [
            {
                "original_filename": "wrong.pdf",
                "detected_type": "executable",
                "accepted": True,
                "reason": "Accepted",
                "text": "unsafe",
                "extracted_name": None,
                "extracted_passport_number": None,
                "extracted_reference": None,
            }
        ],
    )

    result = classify_documents_bounded(
        DocumentMatcher(),
        [("safe.pdf", _blank_pdf(), "other")],
        isolate_pdf_parsing=True,
    )[0]

    assert result.original_filename == "safe.pdf"
    assert result.detected_type == "unknown"
    assert result.accepted is False
    assert result.text == ""
