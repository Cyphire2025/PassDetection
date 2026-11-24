"""Immutable per-operation identity bounds, independent of PDF parsing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DocumentIdentityLimits:
    passenger_identifiers: int
    supplemental_per_passenger: int
    supplemental_per_request: int
    supplemental_inputs: int
