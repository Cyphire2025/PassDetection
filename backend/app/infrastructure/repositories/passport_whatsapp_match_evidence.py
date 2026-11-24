"""Exact evidence merging and bounded PostgreSQL prefilter construction."""

from __future__ import annotations

import unicodedata

from sqlalchemy import Text, cast, func
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.whatsapp.group_submission_matching import IdentityEvidenceValues


def _merge_evidence(
    current: IdentityEvidenceValues,
    incoming: IdentityEvidenceValues,
) -> IdentityEvidenceValues:
    selected_fields: dict[str, frozenset[str]] = {
        key: frozenset(values) for key, values in current.selected_fields.items()
    }
    for key, values in incoming.selected_fields.items():
        selected_fields[key] = selected_fields.get(key, frozenset()) | values
    return IdentityEvidenceValues(
        phones=current.phones | incoming.phones,
        emails=current.emails | incoming.emails,
        passport_numbers=current.passport_numbers | incoming.passport_numbers,
        staff_codes=current.staff_codes | incoming.staff_codes,
        names=current.names | incoming.names,
        selected_fields=selected_fields,
    )


def _ascii_cluster_tokens(
    evidence: IdentityEvidenceValues,
    *,
    token_limit: int,
    token_bytes_limit: int,
) -> tuple[str, ...] | None:
    """Build the PostgreSQL prefilter tokens, or fail closed for non-ASCII data."""

    tokens: set[str] = set()
    for value in evidence.all_values:
        compatible = unicodedata.normalize("NFKC", value)
        if not compatible.isascii():
            return None
        compact = "".join(character for character in compatible.upper() if character.isalnum())
        if len(compact) < 2:
            return None
        tokens.add(compact)
    # The canonical phone normalizer expands a bare 10-digit Indian number to
    # +91.  The stored source value can therefore lack the prefix even though
    # its exact comparison value includes it; include both safe prefilter
    # forms. Exact Python evidence intersection still decides membership.
    for phone in evidence.phones:
        digits = "".join(character for character in phone if character.isdigit())
        if digits.startswith("91") and len(digits) == 12:
            tokens.add(digits[2:])
    if len(tokens) > token_limit:
        return None
    ordered = tuple(sorted(tokens))
    if sum(len(token) for token in ordered) > token_bytes_limit:
        return None
    return ordered


def _canonical_search_corpus(*columns: object) -> ColumnElement[str]:
    # Targeted matching is enabled only on PostgreSQL.  Compacting the corpus
    # makes the SQL prefilter a superset of the exact Python normalizers; exact
    # intersections below discard false positives before they enter the graph.
    joined = func.concat_ws(
        "|",
        *(func.coalesce(cast(column, Text), "") for column in columns),
    )
    return func.regexp_replace(func.upper(joined), "[^A-Z0-9]+", "", "g")


def _token_prefilter(
    corpus: ColumnElement[str],
    tokens: tuple[str, ...],
) -> ColumnElement[bool]:
    # Tokens contain only A-Z/0-9, so one alternation is safe and avoids
    # repeating the relatively expensive canonicalization expression once per
    # evidence value.
    return corpus.op("~")("(" + "|".join(tokens) + ")")
