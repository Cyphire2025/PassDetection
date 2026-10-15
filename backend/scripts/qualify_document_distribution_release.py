"""Exercise the exact image-side release helper on a disposable local database.

The shared qualification harness enforces the synthetic CI database guard and
owns creation/cleanup. Downgrades here affect only that owned test database;
the production release helper never downgrades automatically.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.document_distribution_release import CHAIN, POLICY, SOURCE, TARGET, migration_entries

ROOT = Path(__file__).resolve().parents[1]


def exercise_release_helper(engine: Any, environment: dict[str, str], migrate: Any, message: Any) -> dict[str, object]:
    contract = {**POLICY, "migrations": migration_entries(ROOT)}
    bound_env = {**environment, "MCP_RELEASE_PROOF_SHA256": "a" * 64}

    def invoke(*, capture=False, success=True, extra_env=None):
        args = [sys.executable, "scripts/release_document_distribution_upgrade.py", "--contract-json", json.dumps(contract)]
        if capture:
            args.append("--capture-baseline")
        result = subprocess.run(args, cwd=ROOT, env={**bound_env, **(extra_env or {})},
            text=True, capture_output=True, timeout=240)
        output = json.loads(result.stdout.strip())
        if success:
            assert result.returncode == 0, (output, result.stderr[-2000:])
        else:
            assert result.returncode == 2 and output["status"] == "failed", (output, result.stderr[-2000:])
        assert output["automatic_downgrade"] is False
        return output

    def revision():
        with engine.connect() as connection:
            return connection.scalar(text("SELECT version_num FROM alembic_version"))

    baseline = invoke(capture=True)
    assert baseline["status"] == "baseline_captured"
    bound_env["MCP_RELEASE_BASELINE_SHA256"] = baseline["preservation_sha256"]
    invoke(success=False, extra_env={"MCP_RELEASE_BASELINE_SHA256": "b" * 64})
    assert revision() == SOURCE
    with engine.begin() as held:
        held.execute(text("LOCK TABLE passport_submissions IN ACCESS EXCLUSIVE MODE"))
        invoke(success=False)
        assert held.scalar(text("SELECT version_num FROM alembic_version")) == SOURCE

    # Simulate the first revision having committed before a host interruption.
    migrate("upgrade", CHAIN[0])
    resumed = invoke()
    assert resumed["started_schema"] == CHAIN[0] and resumed["executed_revisions"] == [TARGET]
    assert resumed["preservation_sha256"] == baseline["preservation_sha256"]
    assert resumed["new_columns_null"] and resumed["runtime_grants_verified"]
    assert invoke()["status"] == "already_at_target"
    invoke(capture=True, success=False)

    with engine.begin() as connection:
        connection.execute(text("UPDATE whatsapp_message_logs SET rendered_message='Unexpected mutation' WHERE id=:id"), {"id": message})
    invoke(success=False)
    assert revision() == TARGET
    with engine.begin() as connection:
        connection.execute(text("UPDATE whatsapp_message_logs SET rendered_message='Retained synthetic text' WHERE id=:id"), {"id": message})
        connection.execute(text("CREATE INDEX qualification_unreviewed_idx ON whatsapp_message_logs(status)"))
    invoke(success=False)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX qualification_unreviewed_idx"))
        connection.execute(text("UPDATE whatsapp_message_logs SET document_update_context='{}'::jsonb WHERE id=:id"), {"id": message})
    invoke(success=False)
    with engine.begin() as connection:
        connection.execute(text("UPDATE whatsapp_message_logs SET document_update_context=NULL WHERE id=:id"), {"id": message})
    assert invoke()["status"] == "already_at_target"

    # Separately exercise a complete source-to-target helper application.
    migrate("downgrade", SOURCE)
    assert invoke(capture=True)["preservation_sha256"] == baseline["preservation_sha256"]
    complete = invoke()
    assert complete["executed_revisions"] == list(CHAIN)
    assert complete["preservation_sha256"] == baseline["preservation_sha256"]
    migrate("downgrade", SOURCE)
    return {"original_baseline_retained": True, "source_and_intermediate_resume_passed": True,
        "target_idempotency_passed": True, "invalid_baseline_and_lock_timeout_fail_closed": True,
        "changed_rows_catalog_and_early_new_values_rejected": True,
        "automatic_downgrade": False, "messages_sent": 0}


if __name__ == "__main__":
    from scripts.qualify_document_distribution_upgrade import qualify

    print(json.dumps(qualify(release_helper=True)), flush=True)
