"""Bounded public-flow quality event input."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicFlowTelemetryRequest(BaseModel):
    """Fixed-enum, PII-free client quality/flow signal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event: Literal[
        "visa_photo_rejection",
        "passport_scanner_rejection",
        "public_flow",
    ]
    reason: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
