"""Rehearse a populated PostgreSQL backup, restore, and Alembic upgrade.

This script is intentionally destructive only to two explicitly named,
prefix-validated CI databases. It never targets the configured application
database and it seeds synthetic records only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Support both the existing direct CLI and package imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.postgresql_rehearsal_client import (
    _alembic as _alembic,
)
from scripts.postgresql_rehearsal_client import (
    _client_major as _client_major,
)
from scripts.postgresql_rehearsal_client import (
    _connect as _connect,
)
from scripts.postgresql_rehearsal_client import (
    _create_database as _create_database,
)
from scripts.postgresql_rehearsal_client import (
    _drop_database as _drop_database,
)
from scripts.postgresql_rehearsal_client import (
    _replace_database as _replace_database,
)
from scripts.postgresql_rehearsal_client import (
    _run as _run,
)
from scripts.postgresql_rehearsal_client import (
    _sha256 as _sha256,
)
from scripts.postgresql_rehearsal_client import (
    _timed_stage as _timed_stage,
)
from scripts.postgresql_rehearsal_client import (
    database_environment as database_environment,
)
from scripts.postgresql_rehearsal_client import (
    require_destructive_acknowledgement as require_destructive_acknowledgement,
)
from scripts.postgresql_rehearsal_client import (
    validate_database_name as validate_database_name,
)
from scripts.postgresql_rehearsal_contract import (
    DESTRUCTIVE_ACKNOWLEDGEMENT as DESTRUCTIVE_ACKNOWLEDGEMENT,
)
from scripts.postgresql_rehearsal_contract import (
    EXPECTED_HEAD_REVISION as EXPECTED_HEAD_REVISION,
)
from scripts.postgresql_rehearsal_contract import (
    IDS as IDS,
)
from scripts.postgresql_rehearsal_contract import (
    PRESERVED_TABLES as PRESERVED_TABLES,
)
from scripts.postgresql_rehearsal_contract import (
    PREVIOUS_RELEASE_REVISION as PREVIOUS_RELEASE_REVISION,
)
from scripts.postgresql_rehearsal_contract import (
    PROTECTED_DATABASE_NAMES as PROTECTED_DATABASE_NAMES,
)
from scripts.postgresql_rehearsal_contract import (
    SAFE_DATABASE_NAME as SAFE_DATABASE_NAME,
)
from scripts.postgresql_rehearsal_fixture import (
    _seed_previous_release as _seed_previous_release,
)
from scripts.postgresql_rehearsal_runner import (
    rehearse as rehearse,
)
from scripts.postgresql_rehearsal_snapshot import (
    _assert_constraint_rejected as _assert_constraint_rejected,
)
from scripts.postgresql_rehearsal_snapshot import (
    _assert_snapshot_equal as _assert_snapshot_equal,
)
from scripts.postgresql_rehearsal_snapshot import (
    _previous_release_snapshot as _previous_release_snapshot,
)
from scripts.postgresql_rehearsal_snapshot import (
    _revision as _revision,
)
from scripts.postgresql_rehearsal_snapshot import (
    _row_counts as _row_counts,
)
from scripts.postgresql_rehearsal_snapshot import (
    _scalar as _scalar,
)
from scripts.postgresql_rehearsal_verification import (
    _verify_upgraded_database as _verify_upgraded_database,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-database",
        default="passdetection_ci_previous_release",
    )
    parser.add_argument(
        "--restored-database",
        default="passdetection_ci_restored_release",
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("migration-rehearsal-evidence.json"),
    )
    return parser.parse_args()


def main() -> None:
    arguments = _parse_args()
    backend_root = Path(__file__).resolve().parents[1]
    rehearse(
        backend_root=backend_root,
        evidence_output=arguments.evidence_output.resolve(),
        source_database=arguments.source_database,
        restored_database=arguments.restored_database,
    )


if __name__ == "__main__":
    main()
