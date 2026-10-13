"""User-selected deterministic association rules do not authorize disclosure."""

import pytest

from app.domain.services.traveller_identity import compare_identity, identity_evidence


def evidence(**values):
    return identity_evidence(values)


def test_exact_name_and_two_other_independent_types_match():
    source = evidence(name="  Anil   KUMAR ", passport_no="a0012", dob="1990-01-02")
    saved = evidence(name="Anil Kumar", passport_number="A0012", date_of_birth="1990-01-02")
    result = compare_identity(source, saved)
    assert result.matched and result.matching_types == ("birth_date", "name", "passport")


@pytest.mark.parametrize("changed", [{"name": "Kumar Anil"}, {"dob": "1990-01-03"}, {"passport_no": "A0013"}])
def test_name_or_passport_or_birth_conflict_vetoes_other_agreement(changed):
    fields = {"name": "Anil Kumar", "dob": "1990-01-02", "passport_no": "A0012",
        "phone": "+919876543210", "email": "a@example.test"}
    assert not compare_identity(evidence(**(fields | changed)), evidence(**fields)).matched


def test_multiple_codes_count_once_and_phone_name_alone_never_match():
    fields = {"name": "Anil Kumar", "agent_code": "001", "staff_code": "002", "producer_code": "003"}
    assert not compare_identity(evidence(**fields), evidence(**fields)).matched
    two = evidence(name="Anil Kumar", phone="+919876543210")
    assert not compare_identity(two, two).matched
    three = evidence(**fields, phone="+919876543210")
    assert compare_identity(three, three).matched


def test_present_birth_date_must_be_available_and_match():
    fields = {"name": "Anil Kumar", "phone": "+919876543210", "email": "a@example.test"}
    assert not compare_identity(evidence(**fields, dob="1990-01-02"), evidence(**fields)).matched


def test_alias_conflicts_and_invalid_dates_are_not_silently_ignored():
    assert evidence(name="Person", dob="1990-01-02", date_of_birth="1990-01-03").conflicts == {"birth_date"}
    assert evidence(name="Person", dob="not a date").conflicts == {"birth_date"}
    assert identity_evidence({str(i): "x" for i in range(129)}).conflicts == {"input_limit"}


def test_codes_preserve_zeroes_and_name_keeps_accents_and_order():
    common = {"name": "José Kumar", "phone": "+919876543210"}
    assert not compare_identity(evidence(**common, staff_code="001"), evidence(**common, staff_code="1")).matched
    assert not compare_identity(evidence(**common, staff_code="001"), evidence(name="Jose Kumar", phone=common["phone"], staff_code="001")).matched


def test_email_domain_is_normalized_without_merging_case_sensitive_local_parts():
    assert evidence(email="User@EXAMPLE.TEST").get("email") == {"User@example.test"}
    assert evidence(email="user@example.test").get("email") != evidence(email="User@example.test").get("email")
