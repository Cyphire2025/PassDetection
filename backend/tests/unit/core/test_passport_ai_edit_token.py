from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from app.core.security.passport_ai_edit_token import (
    PassportAiEditTokenError,
    issue_passport_ai_edit_token,
    verify_passport_ai_edit_token,
)


def _scope() -> dict[str, object]:
    return {
        "secret": "test-secret",
        "submission_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "image_type": "visa_photo",
        "expected_revision": 3,
        "source_storage_key": "original/visa.jpg",
        "prompt": "Make the background evenly white",
        "image_content": b"generated-image",
    }


def test_preview_token_is_bound_to_user_revision_prompt_source_and_pixels() -> None:
    scope = _scope()
    with patch("app.core.security.passport_ai_edit_token.time.time", return_value=1000):
        token = issue_passport_ai_edit_token(
            **scope,  # type: ignore[arg-type]
            model="gemini-3-pro-image",
            ttl_seconds=600,
        )
        claims = verify_passport_ai_edit_token(token, **scope)  # type: ignore[arg-type]

    assert claims.submission_id == scope["submission_id"]
    assert claims.expected_revision == 3
    assert claims.model == "gemini-3-pro-image"
    assert claims.expires_at == 1600

    for changed in (
        {"user_id": uuid.uuid4()},
        {"expected_revision": 4},
        {"prompt": "Change something else"},
        {"source_storage_key": "other/visa.jpg"},
        {"image_content": b"tampered-image"},
    ):
        with pytest.raises(PassportAiEditTokenError):
            verify_passport_ai_edit_token(
                token,
                **(scope | changed),  # type: ignore[arg-type]
            )


def test_preview_token_expires_without_exposing_storage_keys_or_prompt() -> None:
    scope = _scope()
    with patch("app.core.security.passport_ai_edit_token.time.time", return_value=1000):
        token = issue_passport_ai_edit_token(
            **scope,  # type: ignore[arg-type]
            model="gemini-3.1-flash-image",
            ttl_seconds=60,
        )

    assert "original/visa.jpg" not in token
    assert "background" not in token
    with (
        patch("app.core.security.passport_ai_edit_token.time.time", return_value=1061),
        pytest.raises(PassportAiEditTokenError, match="expired or changed"),
    ):
        verify_passport_ai_edit_token(token, **scope)  # type: ignore[arg-type]


def test_preview_token_rejects_an_invalid_model_identifier() -> None:
    with pytest.raises(ValueError, match="model identifier"):
        issue_passport_ai_edit_token(
            **_scope(),  # type: ignore[arg-type]
            model="gemini-image\nforged-audit-field",
        )
