from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = BACKEND_ROOT.parent
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "rehearse_postgresql_upgrade.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("postgresql_upgrade_rehearsal", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_database_name_guard_only_allows_explicit_ci_databases() -> None:
    rehearsal = _load_script()

    assert (
        rehearsal.validate_database_name("passdetection_ci_previous_release")
        == "passdetection_ci_previous_release"
    )
    for unsafe_name in (
        "postgres",
        "template0",
        "test_db",
        "passdetection-production",
        "passdetection_ci_../production",
        "PASSDETECTION_CI_RESTORED",
    ):
        with pytest.raises(ValueError):
            rehearsal.validate_database_name(unsafe_name)


def test_database_environment_scopes_alembic_and_postgresql_clients() -> None:
    rehearsal = _load_script()
    base = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "test_db",
        "POSTGRES_USER": "test_user",
        "POSTGRES_PASSWORD": "test_password",
    }

    result = rehearsal.database_environment(base, "passdetection_ci_restored_release")

    assert base["POSTGRES_DB"] == "test_db"
    assert result["POSTGRES_DB"] == "passdetection_ci_restored_release"
    assert result["PGDATABASE"] == "passdetection_ci_restored_release"
    assert result["PGHOST"] == "localhost"
    assert result["PGPORT"] == "5432"
    assert result["PGUSER"] == "test_user"
    assert result["PGPASSWORD"] == "test_password"


def test_destructive_database_operations_require_explicit_acknowledgement() -> None:
    rehearsal = _load_script()

    with pytest.raises(RuntimeError):
        rehearsal.require_destructive_acknowledgement({})

    rehearsal.require_destructive_acknowledgement(
        {rehearsal.DESTRUCTIVE_ACKNOWLEDGEMENT: "1"}
    )


def test_rehearsal_contract_is_previous_release_populated_and_evidence_oriented() -> None:
    rehearsal = _load_script()
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert rehearsal.PREVIOUS_RELEASE_REVISION == "0085_platform_retention_controls"
    assert rehearsal.EXPECTED_HEAD_REVISION == "0090_upload_configuration"
    assert "INSERT INTO attendance_records" in source
    assert "INSERT INTO passport_submissions" in source
    assert "INSERT INTO audit_logs" in source
    assert "--format=custom" in source
    assert "--single-transaction" in source
    assert "production_resilience_proof" in source
    assert "backend-migration-rehearsal:" in workflow
    assert "migration-rehearsal-evidence.json" in workflow
    assert "backend-migration-rehearsal" in workflow.split("docker-build:", maxsplit=1)[1]
