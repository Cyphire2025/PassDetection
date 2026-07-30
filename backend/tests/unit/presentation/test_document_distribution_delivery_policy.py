from __future__ import annotations

from types import SimpleNamespace

from app.presentation.api.v1.routes.document_distribution import (
    _document_delivery_decision,
)


def _delivery(status: str, *, phone: str = "+919999999999", error: str | None = None):
    return SimpleNamespace(
        status=status,
        phone_number=phone,
        error_message=error,
    )


def test_any_prior_success_requires_an_explicit_resend() -> None:
    decision = _document_delivery_decision(
        saved=True,
        match_status="matched",
        recipient_available=True,
        delivery_history=[
            _delivery("failed", error="Provider rejected retry"),
            _delivery("submitted"),
        ],
    )

    assert decision.status == "already_sent"
    assert decision.eligible is False
    assert decision.resend_allowed is True


def test_failed_first_attempt_is_safely_retryable() -> None:
    decision = _document_delivery_decision(
        saved=True,
        match_status="matched",
        recipient_available=True,
        delivery_history=[_delivery("failed", error="Provider rejected request")],
    )

    assert decision.status == "retryable"
    assert decision.eligible is True
    assert decision.error_message == "Provider rejected request"


def test_uncertain_delivery_suppresses_all_resends() -> None:
    decision = _document_delivery_decision(
        saved=True,
        match_status="matched",
        recipient_available=True,
        delivery_history=[_delivery("delivery_unknown")],
    )

    assert decision.status == "delivery_unknown"
    assert decision.eligible is False
    assert decision.resend_allowed is False
