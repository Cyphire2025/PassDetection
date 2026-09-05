"""One SQL membership rule for operational passenger views.

A rejection excludes its source submission. A replacement keeps its source
and excludes the explicitly displaced submissions. Restoring a decision
removes the exclusion immediately; historical attendance rows are untouched.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, and_, exists, or_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import FunctionElement

from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
)


class _JsonContainsSubmission(FunctionElement[bool]):
    type = Boolean()
    inherit_cache = True


@compiles(_JsonContainsSubmission)  # type: ignore[no-untyped-call, untyped-decorator]
def _postgres_contains(element: _JsonContainsSubmission, compiler: SQLCompiler, **kw: Any) -> str:
    values, submission_id = [compiler.process(clause, **kw) for clause in element.clauses]
    return f"({values} @> jsonb_build_array(CAST({submission_id} AS text)))"


@compiles(_JsonContainsSubmission, "sqlite")  # type: ignore[no-untyped-call, untyped-decorator]
def _sqlite_contains(element: _JsonContainsSubmission, compiler: SQLCompiler, **kw: Any) -> str:
    values, submission_id = [compiler.process(clause, **kw) for clause in element.clauses]
    # SQLite stores UUID columns without separators; production PostgreSQL
    # retains their canonical form. Both compare exact normalized identifiers.
    return (
        f"EXISTS (SELECT 1 FROM json_each({values}) AS excluded_passenger "
        f"WHERE replace(excluded_passenger.value, '-', '') = "
        f"replace(CAST({submission_id} AS text), '-', ''))"
    )


def operational_roster_member() -> ColumnElement[bool]:
    """Apply to a statement whose passenger source is PassportSubmissionModel."""
    resolution = PassportRosterResolutionModel
    passenger = PassportSubmissionModel
    exclusion = (
        exists()
        .where(
            resolution.agency_id == passenger.agency_id,
            resolution.client_group_id == passenger.group_id,
            resolution.status == "active",
            or_(
                and_(
                    resolution.resolution_type == "rejected",
                    resolution.submission_id == passenger.id,
                ),
                _JsonContainsSubmission(resolution.excluded_submission_ids, passenger.id),
            ),
        )
        .correlate(PassportSubmissionModel)
    )
    return ~exclusion
