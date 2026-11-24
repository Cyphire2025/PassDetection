"""Saved legacy evidence remains verifiable after local OCR extraction removal."""

from __future__ import annotations

import pytest

from app.infrastructure.ocr.td3_mrz_parser import TD3MRZParser

MRZ = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)


def test_saved_td3_preserves_identity_and_checksum_verified_fields() -> None:
    result = TD3MRZParser().parse(MRZ)

    assert result is not None
    assert result.fields["passport_number"] == "L898902C3"
    assert result.fields["surname"] == "ERIKSSON"
    assert result.fields["given_names"] == "ANNA MARIA"
    assert result.fields["issuing_country"] == "UTO"
    assert result.fields["date_of_birth"] == "1974-08-12"
    assert result.fields["date_of_expiry"] == "2012-04-15"


@pytest.mark.parametrize("raw", [None, "", "unreadable", MRZ[:-1] + "9", MRZ.replace("L898902C3", "L898902C4")])
def test_invalid_saved_evidence_is_rejected_without_ocr_repair(raw: str | None) -> None:
    assert TD3MRZParser().parse(raw) is None
