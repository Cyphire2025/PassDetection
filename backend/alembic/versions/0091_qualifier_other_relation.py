"""Allow explicitly configured custom qualifier relationships.

Revision ID: 0091_qualifier_other_relation
Revises: 0090_upload_configuration
"""

from alembic import op
import sqlalchemy as sa

revision = "0091_qualifier_other_relation"
down_revision = "0090_upload_configuration"
branch_labels = None
depends_on = None

_LEGACY_CODES = (
    "spouse", "husband", "wife", "brother", "sister", "son", "daughter",
    "father", "mother", "parent", "child", "grandfather", "grandmother",
    "grandson", "granddaughter", "father_in_law", "mother_in_law",
    "brother_in_law", "sister_in_law", "son_in_law", "daughter_in_law",
    "legal_guardian",
)
_TABLES = (
    ("qualifier_selections", "relation_code", "relation_label", "ck_qualifier_selections_relation_code", "ck_qualifier_selections_other_text"),
    ("passport_submissions", "qualifier_relation_code", "qualifier_relation_label", "ck_passport_submissions_qualifier_relation_code", "ck_passport_submissions_qualifier_other_text"),
)


def _code_check(column: str, *, allow_other: bool) -> str:
    codes = (*_LEGACY_CODES, "other") if allow_other else _LEGACY_CODES
    values = ", ".join(f"'{code}'" for code in codes)
    return f"{column} IS NULL OR {column} IN ({values})"


def upgrade() -> None:
    # Configuration lives in the existing JSON document. Missing fields retain
    # legacy list=true / other=false defaults; no group settings are rewritten.
    for table, code, label, code_constraint, text_constraint in _TABLES:
        op.alter_column(table, label, existing_type=sa.String(80), type_=sa.String(100))
        op.drop_constraint(code_constraint, table, type_="check")
        op.create_check_constraint(code_constraint, table, _code_check(code, allow_other=True))
        op.create_check_constraint(
            text_constraint,
            table,
            f"{code} <> 'other' OR ({label} IS NOT NULL AND "
            f"length(trim({label})) BETWEEN 1 AND 100 AND lower(trim({label})) <> 'self')",
        )


def downgrade() -> None:
    # A downgrade must not truncate or recategorize passenger-provided answers.
    # Refuse before any DDL if newer data cannot be represented by the old schema.
    connection = op.get_bind()
    for table, code, label, _code_constraint, _text_constraint in _TABLES:
        incompatible = connection.execute(sa.text(
            f"SELECT EXISTS (SELECT 1 FROM {table} "
            f"WHERE {code} = 'other' OR length({label}) > 80)"
        )).scalar()
        if incompatible:
            raise RuntimeError("Cannot downgrade while custom qualifier relationships are stored.")
    for table, code, label, code_constraint, text_constraint in _TABLES:
        op.drop_constraint(text_constraint, table, type_="check")
        op.drop_constraint(code_constraint, table, type_="check")
        op.create_check_constraint(code_constraint, table, _code_check(code, allow_other=False))
        op.alter_column(table, label, existing_type=sa.String(100), type_=sa.String(80))
