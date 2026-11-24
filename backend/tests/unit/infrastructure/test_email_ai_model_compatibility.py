"""Public AI model identities and owner-first registration remain compatible."""

from __future__ import annotations

import importlib
import inspect
import pickle
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from app.infrastructure.database import email_ai_models, model_base

OWNERS = (
    ("rollout", "EmailAiRolloutPolicyModel"),
    ("analyses", "EmailAiAnalysisModel"),
    ("deadlines", "EmailDetectedDeadlineModel"),
    ("proposals", "EmailActionProposalModel"),
    ("drafts", "EmailReplyDraftModel"),
    ("feedback", "EmailAiFeedbackModel"),
)


@pytest.mark.parametrize("owner,name", OWNERS)
def test_email_ai_owner_exposes_the_same_public_mapper_annotations_and_defaults(owner, name):
    module = importlib.import_module(f"app.infrastructure.database._email_ai_models.{owner}")
    cls = getattr(module, name)
    assert cls is getattr(email_ai_models, name)
    assert cls.__module__ == email_ai_models.__name__
    assert cls.__qualname__ == name
    assert cls.__mapper__.class_ is cls
    assert cls.__table__ is model_base.Base.metadata.tables[cls.__tablename__]
    assert model_base.Base.registry._class_registry[name] is cls
    assert pickle.loads(pickle.dumps(cls)) is cls
    assert set(cls.__annotations__) <= set(get_type_hints(cls))
    for column in cls.__table__.columns:
        for kind in ("default", "onupdate"):
            default = getattr(column, kind)
            if default is not None and default.is_callable:
                callback = inspect.unwrap(default.arg)
                if callback.__name__ == "_utcnow":
                    assert callback is email_ai_models._utcnow


@pytest.mark.parametrize("owner,name", OWNERS)
def test_email_ai_owner_first_import_registers_original_order_once(owner, name):
    script = """
import importlib
import inspect
import pickle
import sys
from typing import get_type_hints
from sqlalchemy.orm import configure_mappers

owner = importlib.import_module('app.infrastructure.database._email_ai_models.' + sys.argv[1])
from app.infrastructure.database import email_ai_models as models, model_base, model_registry
configure_mappers()
assert models.Base is model_base.Base is model_registry.Base
assert models.JSONB is model_base.JSONB
cls = getattr(owner, sys.argv[2])
assert cls is getattr(models, sys.argv[2])
assert pickle.loads(pickle.dumps(cls)) is cls
assert set(cls.__annotations__) <= set(get_type_hints(cls))
names = ('EmailAiRolloutPolicyModel', 'EmailAiAnalysisModel', 'EmailDetectedDeadlineModel',
         'EmailActionProposalModel', 'EmailReplyDraftModel', 'EmailAiFeedbackModel')
tables = [getattr(models, name).__tablename__ for name in names]
assert [name for name in models.Base.metadata.tables if name in tables] == tables
namespace = models.Base.registry._class_registry['_sa_module_registry'].mod_ns
for part in models.__name__.split('.'):
    namespace = getattr(namespace, part)
for name in names:
    model = getattr(models, name)
    assert getattr(namespace, name) is model
    assert models.Base.registry._class_registry[name] is model
    assert model.__mapper__.class_ is model
    for column in model.__table__.columns:
        for kind in ('default', 'onupdate'):
            default = getattr(column, kind)
            if default is not None and default.is_callable:
                callback = inspect.unwrap(default.arg)
                if callback.__name__ == '_utcnow':
                    assert callback is models._utcnow
assert len(models.Base.registry.mappers) == len(models.Base.metadata.tables)
print('email AI owner-first registration passed')
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
    assert result.stdout.strip() == "email AI owner-first registration passed"
