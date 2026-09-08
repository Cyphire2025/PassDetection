"""Canonical relation choices for the optional qualifier upload flow."""

from __future__ import annotations

import hashlib
import unicodedata
from enum import Enum
from typing import Any

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.upload_configuration import configuration_for


class QualifierRelation(str, Enum):
    """Stable codes accepted from public clients and persisted on submissions."""

    SPOUSE = "spouse"
    HUSBAND = "husband"
    WIFE = "wife"
    BROTHER = "brother"
    SISTER = "sister"
    SON = "son"
    DAUGHTER = "daughter"
    FATHER = "father"
    MOTHER = "mother"
    PARENT = "parent"
    CHILD = "child"
    GRANDFATHER = "grandfather"
    GRANDMOTHER = "grandmother"
    GRANDSON = "grandson"
    GRANDDAUGHTER = "granddaughter"
    FATHER_IN_LAW = "father_in_law"
    MOTHER_IN_LAW = "mother_in_law"
    BROTHER_IN_LAW = "brother_in_law"
    SISTER_IN_LAW = "sister_in_law"
    SON_IN_LAW = "son_in_law"
    DAUGHTER_IN_LAW = "daughter_in_law"
    LEGAL_GUARDIAN = "legal_guardian"


QUALIFIER_RELATION_LABELS: dict[QualifierRelation, str] = {
    QualifierRelation.SPOUSE: "Spouse",
    QualifierRelation.HUSBAND: "Husband",
    QualifierRelation.WIFE: "Wife",
    QualifierRelation.BROTHER: "Brother",
    QualifierRelation.SISTER: "Sister",
    QualifierRelation.SON: "Son",
    QualifierRelation.DAUGHTER: "Daughter",
    QualifierRelation.FATHER: "Father",
    QualifierRelation.MOTHER: "Mother",
    QualifierRelation.PARENT: "Parent",
    QualifierRelation.CHILD: "Child",
    QualifierRelation.GRANDFATHER: "Grandfather",
    QualifierRelation.GRANDMOTHER: "Grandmother",
    QualifierRelation.GRANDSON: "Grandson",
    QualifierRelation.GRANDDAUGHTER: "Granddaughter",
    QualifierRelation.FATHER_IN_LAW: "Father-in-law",
    QualifierRelation.MOTHER_IN_LAW: "Mother-in-law",
    QualifierRelation.BROTHER_IN_LAW: "Brother-in-law",
    QualifierRelation.SISTER_IN_LAW: "Sister-in-law",
    QualifierRelation.SON_IN_LAW: "Son-in-law",
    QualifierRelation.DAUGHTER_IN_LAW: "Daughter-in-law",
    QualifierRelation.LEGAL_GUARDIAN: "Legal Guardian",
}


def qualifier_relation_options() -> list[dict[str, str]]:
    """Return a presentation-safe ordered copy of the approved allowlist."""

    return [
        {"code": relation.value, "label": QUALIFIER_RELATION_LABELS[relation]}
        for relation in QualifierRelation
    ]


def normalize_qualifier_choice(
    *,
    is_self: bool,
    relation_code: str | None,
    other_relation: str | None = None,
) -> tuple[bool, str | None, str]:
    """Enforce exactly one of Self, a listed relation or explicit Other text."""

    normalized_code = relation_code.strip().casefold() if relation_code else None
    if is_self:
        if normalized_code or other_relation is not None:
            raise ValidationError(
                "Choose either Self or a relationship, not both.",
                field="relation_code",
            )
        return True, None, "Self"
    if normalized_code == "other":
        label = unicodedata.normalize("NFC", other_relation or "").strip()
        if not label or len(label) > 100:
            raise ValidationError(
                "Enter the passenger's relationship using 1 to 100 characters.",
                field="other_relation",
            )
        if label.casefold() == "self":
            raise ValidationError("Choose Self when the qualifier is travelling.", field="other_relation")
        if any(unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"} for character in label):
            raise ValidationError("Enter the relationship on one line.", field="other_relation")
        return False, "other", label
    if other_relation is not None:
        raise ValidationError("Choose Other to enter a relationship.", field="other_relation")
    if not normalized_code:
        raise ValidationError(
            "Choose the passenger's relationship with the qualifier.",
            field="relation_code",
        )
    try:
        relation = QualifierRelation(normalized_code)
    except ValueError as exc:
        raise ValidationError(
            "Choose an approved family relationship.",
            field="relation_code",
        ) from exc
    return False, relation.value, QUALIFIER_RELATION_LABELS[relation]


def require_enabled_qualifier_choice(group: Any, *, is_self: bool, relation_code: str | None) -> None:
    """Recheck current link settings before accepting an unconsumed choice."""
    if not getattr(group, "relation_with_qualifier_enabled", False):
        raise ValidationError(
            "Relation with Qualifier is not enabled for this upload link.",
            field="qualifier_selection_token",
        )
    if is_self:
        return
    config = configuration_for(group)
    enabled = (
        config.qualifier_relation_other_enabled
        if relation_code == "other"
        else config.qualifier_relation_list_enabled
    )
    if not enabled:
        raise ValidationError(
            "This relationship entry option is no longer enabled. Please choose again.",
            field="qualifier_selection_token",
        )


def hash_qualifier_selection_token(token: str) -> str:
    """Hash the public bearer token before repository lookup or persistence."""

    normalized = token.strip()
    if not 32 <= len(normalized) <= 256:
        raise ValidationError(
            "The qualifier selection token is invalid.",
            field="qualifier_selection_token",
        )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
