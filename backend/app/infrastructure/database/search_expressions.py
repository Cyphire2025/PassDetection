"""Literal substring search with an indexable, non-authoritative prefilter.

The concatenated expression matches migration0110's PostgreSQL trigram index.
Exact per-field predicates remain mandatory: text spanning two fields must not
be treated as a match. Two-character searches retain their existing behavior,
although PostgreSQL may choose a scoped scan for such low-selectivity input.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import and_, func, literal, or_
from sqlalchemy.sql.elements import ColumnElement, SQLColumnExpression

from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel


def literal_substring(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def passport_search_fields(
    *, include_given_names: bool = True
) -> tuple[SQLColumnExpression[str | None], ...]:
    model = PassportSubmissionModel
    fields = (model.client_name, model.client_email, model.client_phone, model.departure_city)
    names = (
        ("passport_number", "surname", "given_names")
        if include_given_names
        else ("passport_number", "surname")
    )
    return (
        *fields,
        *(
            column[name].as_string()
            for name in names
            for column in (model.extracted_fields, model.confirmed_fields)
        ),
    )


def group_search_fields() -> tuple[SQLColumnExpression[str | None], ...]:
    return (ClientGroupModel.name, ClientGroupModel.destination)


def searchable_text(fields: Sequence[SQLColumnExpression[str | None]]) -> ColumnElement[str]:
    expression: ColumnElement[str] = func.coalesce(fields[0], "")
    for field in fields[1:]:
        expression = expression + literal("\x1f") + func.coalesce(field, "")
    return func.lower(expression)


def substring_predicate(
    query: str,
    *,
    fields: Sequence[SQLColumnExpression[str | None]],
    indexed_fields: Sequence[SQLColumnExpression[str | None]] | None = None,
) -> ColumnElement[bool]:
    pattern = literal_substring(query.lower())
    return and_(
        searchable_text(indexed_fields or fields).like(pattern, escape="\\"),
        or_(*(func.lower(field).like(pattern, escape="\\") for field in fields)),
    )
