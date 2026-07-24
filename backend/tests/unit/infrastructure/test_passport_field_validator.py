from app.infrastructure.validation.passport_field_validator import (
    PassportFieldValidator,
)


def _valid_fields() -> dict[str, str]:
    return {
        "surname": "DOE",
        "given_names": "JANE",
        "passport_number": "P1234567",
        "nationality": "USA",
        "place_of_issue": "NEW YORK / JFK",
        "date_of_birth": "1990-01-01",
        "date_of_expiry": "2099-01-01",
        "sex": "F",
    }


def test_place_of_issue_is_validated_as_visible_free_text() -> None:
    result = PassportFieldValidator().validate(_valid_fields())

    assert result.status == "valid"
    assert result.issues == []


def test_place_of_issue_rejects_control_characters() -> None:
    fields = _valid_fields()
    fields["place_of_issue"] = "NEW\x00YORK"

    result = PassportFieldValidator().validate(fields)

    assert result.status == "review_required"
    assert [issue.field for issue in result.issues] == ["place_of_issue"]
