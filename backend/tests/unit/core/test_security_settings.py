from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config.settings import JWTSettings


def test_jwt_algorithm_is_pinned_to_reviewed_hs256_profile() -> None:
    assert JWTSettings(_env_file=None).algorithm == "HS256"

    with pytest.raises(PydanticValidationError):
        JWTSettings(algorithm="ES256", _env_file=None)  # type: ignore[arg-type]
