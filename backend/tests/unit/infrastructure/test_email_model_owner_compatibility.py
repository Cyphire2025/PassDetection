"""Legacy email ORM identities remain usable through each focused table owner."""

from __future__ import annotations

import importlib
import pickle
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import pytest
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from app.infrastructure.database import email_models, model_base

OWNERS = (
    ("connections", "EmailConnectionModel"),
    ("oauth", "EmailOAuthStateModel"),
    ("messages", "EmailMessageModel"),
    ("artifacts", "EmailArtifactModel"),
    ("documents", "EmailArtifactDocumentModel"),
    ("reviews", "EmailReviewItemModel"),
    ("activity", "EmailActivityEventModel"),
)


@pytest.mark.parametrize("owner,name", OWNERS)
def test_email_owner_retains_legacy_class_identity_annotations_and_compilable_schema(owner, name):
    module = importlib.import_module(f"app.infrastructure.database._email_models.{owner}")
    cls = getattr(module, name)
    assert cls is getattr(email_models, name)
    assert cls.__module__ == email_models.__name__
    assert cls.__qualname__ == name
    assert cls.__table__ is model_base.Base.metadata.tables[cls.__tablename__]
    assert cls.__mapper__.class_ is cls
    assert model_base.Base.registry._class_registry[name] is cls
    assert pickle.loads(pickle.dumps(cls)) is cls
    assert set(cls.__annotations__) <= set(get_type_hints(cls))
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        assert f"CREATE TABLE {cls.__tablename__}" in str(CreateTable(cls.__table__).compile(dialect=dialect))
        for index in cls.__table__.indexes:
            compiled = str(CreateIndex(index).compile(dialect=dialect))
            assert str(index.name) in compiled


@pytest.mark.parametrize("owner,name", OWNERS)
def test_each_email_owner_can_be_the_first_import_without_duplicate_registration(owner, name):
    script = """
import importlib
import inspect
import pickle
import sys
from typing import get_type_hints
from sqlalchemy import event
from sqlalchemy.orm import configure_mappers

owner = importlib.import_module('app.infrastructure.database._email_models.' + sys.argv[1])
from app.infrastructure.database import email_models, model_base, model_registry

configure_mappers()
cls = getattr(owner, sys.argv[2])
assert getattr(email_models, sys.argv[2]) is cls
assert pickle.loads(pickle.dumps(cls)) is cls
assert set(cls.__annotations__) <= set(get_type_hints(cls))
assert email_models.Base is model_base.Base is model_registry.Base
assert email_models.JSONB is model_base.JSONB
assert len(model_base.Base.registry.mappers) == len(model_base.Base.metadata.tables)
for name in ('EmailConnectionModel', 'EmailMessageModel', 'EmailArtifactModel',
             'EmailArtifactDocumentModel', 'EmailReviewItemModel', 'EmailActivityEventModel'):
    target = getattr(email_models, name)
    assert event.contains(target, 'before_update', email_models._reject_email_owner_change)
    assert len(tuple(target.__mapper__.dispatch.before_update)) == 1
assert not event.contains(email_models.EmailOAuthStateModel, 'before_update', email_models._reject_email_owner_change)
default = email_models.EmailConnectionModel.__table__.c.normalized_email_address.default.arg
assert inspect.unwrap(default) is email_models._normalized_email_default
print('email owner-first registration passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, owner, name],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "email owner-first registration passed"
