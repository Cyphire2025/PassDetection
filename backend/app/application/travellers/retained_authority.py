"""One retained-authority rule, identical in SQL and object checks.

Operational authority permits internal assignment; it does not prove a public
claim or record the traveller's personal consent. Malformed evidence fails closed.
"""
from typing import Any

from sqlalchemy import Boolean, String, and_, func, or_
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.functions import FunctionElement

from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel

OPERATOR_REGISTRATION_VERSION = "operator_history_v1"
OPERATOR_STAFF_RECORD_VERSION = "operator_staff_record_v1"
_WHITESPACE = " \t\r\n\v\f"


class _JsonType(FunctionElement[str]):
    type = String()
    inherit_cache = True


@compiles(_JsonType, "postgresql")  # type: ignore[no-untyped-call,untyped-decorator]
def _pg_type(element: Any, compiler: Any, **kwargs: Any) -> str:
    return f"jsonb_typeof({compiler.process(list(element.clauses)[0], **kwargs)})"


@compiles(_JsonType, "sqlite")  # type: ignore[no-untyped-call,untyped-decorator]
def _sqlite_type(element: Any, compiler: Any, **kwargs: Any) -> str:
    return f"json_type({compiler.process(list(element.clauses)[0], **kwargs)})"


class _PositiveRevision(FunctionElement[bool]):
    type = Boolean()
    inherit_cache = True


@compiles(_PositiveRevision, "postgresql")  # type: ignore[no-untyped-call,untyped-decorator]
def _pg_revision(element: Any, compiler: Any, **kwargs: Any) -> str:
    evidence = compiler.process(list(element.clauses)[0], **kwargs)
    value = f"({evidence} ->> 'policy_revision')"
    # CASE guards the cast even if the planner reorders surrounding predicates.
    # At most ten digits fit bigint; malformed/decimal values never cast.
    return (f"(CASE WHEN jsonb_typeof({evidence} -> 'policy_revision') = 'number' "
            f"AND {value} ~ '^[1-9][0-9]{{0,9}}$' THEN "
            f"CAST({value} AS bigint) BETWEEN 1 AND 2147483647 ELSE false END)")


@compiles(_PositiveRevision, "sqlite")  # type: ignore[no-untyped-call,untyped-decorator]
def _sqlite_revision(element: Any, compiler: Any, **kwargs: Any) -> str:
    evidence = compiler.process(list(element.clauses)[0], **kwargs)
    return (f"(json_type({evidence}, '$.policy_revision') = 'integer' AND "
            f"json_extract({evidence}, '$.policy_revision') BETWEEN 1 AND 2147483647)")


def _nonblank_sql(evidence: Any, field: str) -> ColumnElement[bool]:
    return and_(_JsonType(evidence[field]).in_(("string", "text")),
                func.trim(evidence[field].as_string(), _WHITESPACE) != "")


def retained_authority_predicate() -> ColumnElement[bool]:
    person = TravellerProfileModel
    evidence = person.reuse_permission_evidence
    operator = or_(
        and_(evidence["authority_kind"].as_string() == OPERATOR_REGISTRATION_VERSION,
             _PositiveRevision(evidence)),
        and_(evidence["authority_kind"].as_string() == OPERATOR_STAFF_RECORD_VERSION,
             _nonblank_sql(evidence, "reason"), _nonblank_sql(evidence, "source")),
    )
    return and_(person.status == "active", person.deleted_at.is_(None),
        _JsonType(evidence) == "object", or_(
            and_(person.reuse_permission_status == "granted", evidence != {}),
            and_(person.reuse_permission_status == "unknown",
                 _nonblank_sql(evidence, "actor_user_id"), operator)))


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip(_WHITESPACE))


def has_retained_authority(person: TravellerProfileModel) -> bool:
    if person.status != "active" or person.deleted_at is not None:
        return False
    evidence = person.reuse_permission_evidence
    if not isinstance(evidence, dict) or not evidence:
        return False
    if person.reuse_permission_status == "granted":
        return True
    if person.reuse_permission_status != "unknown" or not _nonblank(evidence.get("actor_user_id")):
        return False
    if evidence.get("authority_kind") == OPERATOR_REGISTRATION_VERSION:
        revision = evidence.get("policy_revision")
        return type(revision) is int and 1 <= revision <= 2147483647
    return bool(evidence.get("authority_kind") == OPERATOR_STAFF_RECORD_VERSION
                and _nonblank(evidence.get("reason")) and _nonblank(evidence.get("source")))
