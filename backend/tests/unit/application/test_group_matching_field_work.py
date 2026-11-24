"""Selected-heading matching retains exact policy with linear metadata parsing."""

from __future__ import annotations

import importlib

import pytest

from app.application.use_cases.whatsapp.group_submission_matching import _mapping_field_values


@pytest.mark.parametrize(
    ("heading", "expected"),
    [("agent_code", ["primary", "alternate"]), ("terminal_2", ["terminal-specific"])],
)
def test_conflicting_heading_parsing_scales_with_input_not_each_metadata_pair(
    monkeypatch: pytest.MonkeyPatch, heading: str, expected: list[str],
) -> None:
    metadata = {f"metadata_{index}": f"value-{index}" for index in range(40)}
    metadata.update({
        "agent_code": "primary", "agent_code_2": "alternate",
        "terminal_2": "terminal-specific",
        "duplicate_conflicting_fields": ",".join(["agent_code", *[f"other_{index}" for index in range(20)]]),
    })
    owner = importlib.import_module(_mapping_field_values.__module__)
    normalize = owner._normalized_key
    visits = 0

    def counted(value: object) -> str:
        nonlocal visits
        visits += 1
        return normalize(value)

    monkeypatch.setattr(owner, "_normalized_key", counted)
    assert _mapping_field_values(metadata, heading) == expected
    # Includes heading normalization, both checks for each conflict token and
    # every metadata key. Re-parsing all conflicts for every key is quadratic.
    assert visits <= 4 * len(metadata)
