"""Stable shared GC model identity and existing descriptor/default behavior."""

from __future__ import annotations

import inspect
import pickle
import uuid
from datetime import UTC, datetime
from typing import get_type_hints
from urllib.parse import parse_qs, urlsplit

import pytest

from app.infrastructure.database import gc_mobile_models as public
from app.infrastructure.database import model_base


def _models():
    return [
        value
        for value in vars(public).values()
        if isinstance(value, type)
        and value.__module__ == public.__name__
        and hasattr(value, "__table__")
    ]


def test_explicit_and_star_exports_keep_original_qualified_registry_identity():
    assert public.Base is model_base.Base
    assert public.JSONB is model_base.JSONB
    assert len(_models()) == 23
    assert len(public.__all__) == 22
    assert "MobileAppAttestKeyModel" not in public.__all__
    assert public.MobileAppAttestKeyModel in _models()
    namespace = public.Base.registry._class_registry["_sa_module_registry"].mod_ns
    for component in public.__name__.split("."):
        namespace = getattr(namespace, component)
    for model in _models():
        assert getattr(namespace, model.__name__) is model
        assert public.Base.registry._class_registry[model.__name__] is model
        assert model.__table__ is public.Base.metadata.tables[model.__tablename__]
        assert pickle.loads(pickle.dumps(model)) is model
        assert str(inspect.signature(model)) == "(**kwargs)"
        assert get_type_hints(model)


def test_all_gc_clock_defaults_keep_the_legacy_live_clock_binding(monkeypatch):
    fixed = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

    class FrozenClock:
        @staticmethod
        def now(*, tz):
            assert tz is UTC
            return fixed

    monkeypatch.setattr(public, "datetime", FrozenClock)
    assert public._utcnow() is fixed
    checked = 0
    for model in _models():
        for column in model.__table__.columns:
            for default in (column.default, column.onupdate):
                if (
                    default is not None
                    and inspect.unwrap(getattr(default, "arg", None)) is public._utcnow
                ):
                    assert default.arg(None) is fixed
                    checked += 1
    assert checked == 65
    assert public._utcnow is not model_base._utcnow
    assert pickle.loads(pickle.dumps(public._utcnow)) is public._utcnow


@pytest.mark.parametrize("key", [None, "private/synthetic-logo-revision.png"])
def test_company_logo_descriptor_keeps_lazy_private_url_behavior(key):
    company_id, agency_id = uuid.uuid4(), uuid.uuid4()
    company = public.ClientOrganizationModel(
        id=company_id,
        agency_id=agency_id,
        logo_image_key=key,
    )
    descriptor = vars(public.ClientOrganizationModel)["logo_url"]
    assert isinstance(descriptor, property)
    assert descriptor.fget.__module__ == public.__name__
    if key is None:
        assert company.logo_url is None
    else:
        address = urlsplit(company.logo_url)
        assert address.path == f"/api/v1/branding/company-logo/{company_id}"
        assert parse_qs(address.query) == {
            "agency_id": [str(agency_id)],
            "v": ["synthetic-logo-revision"],
        }
        assert "private/" not in company.logo_url
