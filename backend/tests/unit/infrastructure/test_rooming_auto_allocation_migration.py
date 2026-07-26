from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_migration() -> object:
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0058_rooming_auto_allocation.py"
    )
    spec = importlib.util.spec_from_file_location("rooming_auto_migration", path)
    if spec is None or spec.loader is None:
        raise AssertionError("Could not load rooming auto-allocation migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rooming_auto_allocation_migration_follows_current_head() -> None:
    migration = _load_migration()
    assert migration.revision == "0058_rooming_auto"
    assert migration.down_revision == "0057_meal_categories"


def test_migration_enforces_exclusive_membership_and_safe_legacy_backfill() -> None:
    path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0058_rooming_auto_allocation.py"
    )
    source = path.read_text(encoding="utf-8")

    assert '"rooming_hotel_passengers"' in source
    assert '"group_id",\n            "passenger_id"' in source
    assert "uq_rooming_hotel_passengers_group_passenger" in source
    assert "allocation_priority_fields" in source
    assert "allocation_revision" in source
    assert "allocation_fingerprint" in source
    assert "FROM rooming_checkins AS checkin" in source
    assert "ROW_NUMBER() OVER" in source
