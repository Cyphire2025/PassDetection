"""Populated 0107 -> 0108 rehearsal on an explicitly isolated local CI database.

Requires a pre-created empty/current-0107 passdetection_ci_phase2_* database.
No database, table, object, or row is deleted by this qualifier. Synthetic
invalid-row probes are reset by transaction rollback. Retain the database for
inspection; cleanup is a separate operator decision.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config.settings import get_settings  # noqa: E402
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel  # noqa: E402
from app.infrastructure.database.models import (  # noqa: E402
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database.sync_url)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    database = os.environ.get("POSTGRES_DB", "")
    if not database.startswith("passdetection_ci_phase2_"):
        raise RuntimeError("Explicit isolated phase-two CI database required")
    with engine.connect() as connection:
        if connection.scalar(text("SELECT current_database()")) != database:
            raise RuntimeError("Database identity mismatch")
        if connection.scalar(text("SELECT version_num FROM alembic_version")) != "0107_passport_ecr_checks":
            raise RuntimeError("Qualifier requires the retained 0107 baseline")
    agency, other, group, passport, batch, item = (uuid.uuid4() for _ in range(6))
    with Session(engine) as session:
        session.add_all([AgencyModel(id=agency, name="Synthetic owner", email=f"{agency}@example.test"),
                         AgencyModel(id=other, name="Other owner", email=f"{other}@example.test")])
        session.flush()
        session.add(ClientGroupModel(id=group, agency_id=agency, name="Synthetic group",
                                     token=f"synthetic-{group}", status="active"))
        session.add(EcrBatchModel(id=batch, agency_id=agency, title="Synthetic ECR", expected_count=1))
        session.flush()
        session.add(PassportSubmissionModel(id=passport, agency_id=agency, group_id=group,
                                           client_name="Synthetic traveller", image_s3_key="synthetic"))
        session.add(EcrItemModel(id=item, batch_id=batch, client_id=uuid.uuid4(),
                                original_filename="synthetic.jpg", content_type="image/jpeg",
                                sha256="0" * 64, status="completed", result="ECR", attempts=2))
        session.commit()

    spec = importlib.util.spec_from_file_location("data_invariants_migration",
                                               ROOT / "alembic/versions/0108_data_invariants.py")
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    probes = (
        ("passport_submissions", passport, "agency_id = :other", "fk_passport_submissions_group_agency"),
        ("ecr_batches", batch, "status = 'unknown'", "ck_ecr_batch_status"),
        ("ecr_items", item, "status = 'unknown'", "ck_ecr_item_status"),
        ("ecr_items", item, "result = 'unknown'", "ck_ecr_item_result"),
        ("ecr_items", item, "input_tokens = -1", "ck_ecr_item_counters"),
        ("ecr_items", item, "output_tokens = -1", "ck_ecr_item_counters"),
        ("ecr_items", item, "attempts = -1", "ck_ecr_item_counters"),
        ("ecr_items", item, "result = NULL", "ck_ecr_item_outcome"),
        ("ecr_items", item, "status = 'queued'", "ck_ecr_item_outcome"),
        ("ecr_items", item, "status = 'failed'", "ck_ecr_item_outcome"),
    )
    passed: list[str] = []
    for table, identifier, assignment, expected in probes:
        # The outer transaction owns only a synthetic invalid probe. The failed
        # migration rolls back to a savepoint, letting us verify row preservation
        # before rolling back the invalid probe itself.
        with engine.connect() as connection:
            outer = connection.begin()
            connection.execute(text(f"UPDATE {table} SET {assignment} WHERE id = :id"),
                               {"id": identifier, "other": other})
            before = _snapshot(connection)
            nested = connection.begin_nested()
            migration.op = Operations(MigrationContext.configure(connection))
            try:
                migration.upgrade()
            except Exception as error:
                nested.rollback()
                if "0108 preflight" not in str(error) or expected not in str(error):
                    raise RuntimeError("Wrong migration rejection") from None
            else:
                raise RuntimeError("Invalid retained data was unexpectedly accepted")
            if _snapshot(connection) != before:
                raise RuntimeError("Failed migration changed retained records")
            passed.append(f"{table}:{assignment.split('=')[0].strip()}:{expected}")
            outer.rollback()
    with engine.connect() as connection:
        before = _snapshot(connection)
    command.upgrade(config, "0108_data_invariants")
    with engine.connect() as connection:
        after = _snapshot(connection)
        if before != after:
            raise RuntimeError("Successful upgrade changed retained records")
        actual = connection.execute(text("SELECT conname, convalidated FROM pg_constraint "
            "WHERE conname = 'fk_passport_submissions_group_agency' OR "
            "conname IN ('ck_ecr_batch_status','ck_ecr_item_status','ck_ecr_item_result',"
            "'ck_ecr_item_counters','ck_ecr_item_outcome') ORDER BY conname")).all()
        if len(actual) != 6 or not all(row[1] for row in actual):
            raise RuntimeError("Missing or unvalidated constraints")
    print(json.dumps({"scope": "synthetic local PostgreSQL only", "from": "0107_passport_ecr_checks",
                      "to": "0108_data_invariants", "invalid_upgrade_probes": passed,
                      "retained_table_digests": after, "validated_constraints": [r[0] for r in actual],
                      "rows_deleted": 0, "production_changed": False}, indent=2))
    engine.dispose()
    return 0


def _snapshot(connection) -> dict[str, dict[str, object]]:
    result = {}
    for table in ("agencies", "client_groups", "passport_submissions", "ecr_batches", "ecr_items"):
        rows = connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t ORDER BY id")).scalars().all()
        result[table] = {"count": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest()}
    return result


if __name__ == "__main__":
    raise SystemExit(main())
