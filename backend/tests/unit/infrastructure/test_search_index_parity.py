"""Changing a search expression without its physical index is a regression."""

import importlib.util
from pathlib import Path

from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateIndex

from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.search_expressions import (
    group_search_fields,
    passport_search_fields,
    searchable_text,
)
from app.infrastructure.database.search_index_sql import GROUP_SEARCH_SQL, PASSPORT_SEARCH_SQL


def test_query_metadata_and_frozen_migration_use_identical_index_expressions():
    path = Path(__file__).resolve().parents[3] / "alembic/versions/0110_search_indexes.py"
    spec = importlib.util.spec_from_file_location("search_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    for (table, name, frozen), model, fields in zip(migration.INDEXES,
            (PassportSubmissionModel, ClientGroupModel), (passport_search_fields(), group_search_fields()), strict=True):
        query = str(searchable_text(fields).compile(dialect=dialect(), compile_kwargs={"literal_binds": True})).replace(table + ".", "")
        assert query == frozen
        index = next(index for index in model.__table__.indexes if index.name == name)
        ddl = str(CreateIndex(index).compile(dialect=dialect()))
        canonical = PASSPORT_SEARCH_SQL if table == "passport_submissions" else GROUP_SEARCH_SQL
        assert canonical in ddl and "USING gin" in ddl and "gin_trgm_ops" in ddl
