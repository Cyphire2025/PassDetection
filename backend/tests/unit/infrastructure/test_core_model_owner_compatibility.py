"""Core model ownership retains the published ORM and Python contracts."""

from __future__ import annotations

import importlib
import pickle
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from app.infrastructure.database import model_base, models

OWNERS = (
    ("identity", ("AgencyModel", "UserModel", "RefreshTokenModel")),
    ("groups", ("ClientGroupModel",)),
    ("access", ("ManagerGroupAccessModel", "CoordinatorAssignmentModel", "CoordinatorGroupAssignmentModel")),
    ("passport", ("PassportSubmissionModel",)),
    ("exports", ("PassportExportHistoryModel",)),
    ("roster", ("PassportRosterResolutionModel",)),
    ("images", ("PassportImageCropModel", "PassportVisaAiImageModel", "PassportVisaAiImageJobModel")),
    ("upload_workflow", ("QualifierSelectionModel", "PassportProcessingJobModel")),
    ("broadcast_links", ("ClientGroupWhatsAppBroadcastLinkModel",)),
    ("verification_jobs", ("PassportPostSubmissionVerificationJobModel",)),
    ("audit", ("AuditChainHeadModel", "AuditLogModel")),
    ("notifications", ("NotificationModel",)),
    ("platform", ("PlatformSettingModel",)),
)


@pytest.mark.parametrize("owner,names", OWNERS)
def test_private_owner_exports_are_the_public_mapped_classes(owner, names):
    module = importlib.import_module(f"app.infrastructure.database._core_models.{owner}")
    for name in names:
        cls = getattr(module, name)
        assert getattr(models, name) is cls
        assert cls.__module__ == models.__name__
        assert cls.__qualname__ == name
        assert cls.__table__ is model_base.Base.metadata.tables[cls.__tablename__]
        assert model_base.Base.registry._class_registry[name] is cls
        assert pickle.loads(pickle.dumps(cls)) is cls


@pytest.mark.parametrize(
    "name",
    [name for _, names in OWNERS for name in names if name != "ClientGroupModel"]
    + ["PlatformSettingsValue"],
)
def test_resolvable_public_annotations_use_the_legacy_module_namespace(name):
    # The metadata comparison records ClientGroupModel's preexisting unresolved
    # ClientOrganizationModel reference separately from the successful cases.
    cls = getattr(models, name)
    assert set(cls.__annotations__) <= set(get_type_hints(cls))


def test_private_owner_can_be_the_first_database_import_in_a_fresh_process():
    script = """
import importlib
import pickle
from typing import get_type_hints
from sqlalchemy.orm import configure_mappers

owner = importlib.import_module('app.infrastructure.database._core_models.passport')
from app.infrastructure.database import model_base, model_registry, models

configure_mappers()
assert owner.PassportSubmissionModel is models.PassportSubmissionModel
assert models.Base is model_registry.Base is model_base.Base
assert models.JSONB is model_base.JSONB
assert models._utcnow is model_base._utcnow
assert pickle.loads(pickle.dumps(owner.PassportSubmissionModel)) is owner.PassportSubmissionModel
assert 'group' in get_type_hints(owner.PassportSubmissionModel)
assert len(models.Base.registry.mappers) == len(models.Base.metadata.tables)
print('owner-first model registration passed')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "owner-first model registration passed"
