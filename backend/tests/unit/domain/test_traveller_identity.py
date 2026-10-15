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


@pytest.mark.parametrize("changed", [{"name": "Sunil Kumar"}, {"dob": "1990-01-03"}, {"passport_no": "A0013"}])
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


@pytest.mark.parametrize("birth", ["1990-01-02 00:00:00", "1990-01-02T00:00:00", "1990-01-02 00:00:00.000000"])
def test_excel_midnight_birth_date_matches_the_saved_calendar_date(birth):
    source = evidence(name="Anil Kumar", passport_number="A0012", dob=birth, date_of_birth="1990-01-02")
    saved = evidence(name="Anil Kumar", passport_number="A0012", date_of_birth="1990-01-02")
    result = compare_identity(source, saved)
    assert result.matched and result.matching_types == ("birth_date", "name", "passport")


@pytest.mark.parametrize("birth", ["1990-01-02 12:00:00", "1990-01-02T00:00:00Z",
    "1990-01-02 00:00:00+05:30", "1990-02-30 00:00:00", "01/02/1990", "32875"])
def test_birth_date_matching_does_not_guess_unsupported_excel_or_timezone_values(birth):
    source = evidence(name="Anil Kumar", passport_number="A0012", phone="+919876543210", dob=birth)
    saved = evidence(name="Anil Kumar", passport_number="A0012", phone="+919876543210", dob="1990-01-02")
    assert source.conflicts == {"birth_date"}
    assert not compare_identity(source, saved).matched


@pytest.mark.parametrize("incoming,saved_name", [
    ("Synthetic Kumar", "Synthetic Kumar Kumar"),
    ("Synthetic", "Synthetic Middle Family"),
    ("Synthetic Middle Family", "Synthetic Family"),
    (" Kumar Anil ", "Anil Kumar"),
])
def test_whole_word_partial_names_require_passport_and_two_more_types(incoming, saved_name):
    fields = {"passport_number": "P001234", "phone": "+919876543210", "email": "person@example.test"}
    result = compare_identity(evidence(name=incoming, **fields), evidence(name=saved_name, **fields))
    assert result.matched and result.reason == "corroborated_partial_name_match"
    assert result.matching_types == ("email", "name", "passport", "phone")


@pytest.mark.parametrize("fields", [
    {"phone": "+919876543210", "email": "a@example.test", "staff_code": "42"},
    {"passport_number": "P1234", "phone": "+919876543210"},
    {"passport_number": "P1234", "staff_code": "42", "agent_code": "42", "producer_code": "42"},
])
def test_partial_name_cannot_use_shared_phone_or_multiple_codes_as_extra_proof(fields):
    assert not compare_identity(evidence(name="Anil", **fields), evidence(name="Anil Kumar", **fields)).matched


@pytest.mark.parametrize("change", [{"name": "Sunil"}, {"name": "Ani"},
    {"passport_number": "OTHER12"}, {"date_of_birth": "1991-01-02"}])
def test_partial_name_rejects_wrong_holder_substrings_and_identity_conflicts(change):
    fields = {"name": "Anil", "passport_number": "P1234", "date_of_birth": "1990-01-02",
        "phone": "+919876543210", "email": "a@example.test"}
    assert not compare_identity(evidence(**(fields | change)), evidence(**(fields | {"name": "Anil Kumar"}))).matched


def test_authoritative_reviewed_name_replaces_only_name_aliases():
    result = identity_evidence({"full name": "Old Entered Name", "name": "Other Alias",
        "passport_number": "P1234", "dob": "1990-01-01", "date_of_birth": "1990-01-02"},
        name="Original trip label", authoritative_name="Reviewed Passport Name")
    assert result.get("name") == {"reviewed passport name"}
    assert result.conflicts == {"birth_date"}
