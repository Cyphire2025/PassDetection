from __future__ import annotations

import copy
import json
from unittest.mock import Mock

import pytest
from qa import qualify_document_migration as qualifier


def result():
    return {"source": qualifier.SOURCE, "target": qualifier.TARGET,
        "upgrade_and_retry_passed": True, "lock_timeout_atomic_rollback_passed": True,
        "orm_read_write_rollback_passed": True, "downgrade_reupgrade_passed": True,
        "preexisting_rows_and_fields_retained": True, "synthetic_only": True, "messages_sent": 0,
        "release_helper": {"original_baseline_retained": True, "source_and_intermediate_resume_passed": True,
            "target_idempotency_passed": True, "invalid_baseline_and_lock_timeout_fail_closed": True,
            "changed_rows_catalog_and_early_new_values_rejected": True,
            "automatic_downgrade": False, "messages_sent": 0}}


def encode(value, contract="a" * 64):
    return qualifier.MARKER + json.dumps({"source_contract_sha256": contract, "result": value})


def test_only_complete_image_bound_result_is_admitted():
    value = result()
    assert qualifier.validate_result(encode(value), "a" * 64) == value


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(source="0137_company_directory"),
    lambda row: row.update(upgrade_and_retry_passed=False),
    lambda row: row.update(synthetic_only=1),
    lambda row: row.update(messages_sent=False),
    lambda row: row.update(messages_sent=1),
    lambda row: row["release_helper"].update(original_baseline_retained=False),
    lambda row: row["release_helper"].update(source_and_intermediate_resume_passed=False),
    lambda row: row["release_helper"].update(target_idempotency_passed=False),
    lambda row: row["release_helper"].update(automatic_downgrade=True),
])
def test_missing_or_weakened_checks_fail_closed(mutation):
    value = copy.deepcopy(result())
    mutation(value)
    with pytest.raises(ValueError, match="incomplete_document_migration_proof"):
        qualifier.validate_result(encode(value), "a" * 64)


def test_duplicate_or_unbound_results_rejected():
    raw = encode(result())
    for output, digest in [(raw + "\n" + raw, "a" * 64), (raw, "b" * 64), ("", "a" * 64)]:
        with pytest.raises(ValueError, match="one_bound_migration_result_required"):
            qualifier.validate_result(output, digest)


def test_exact_receipt_only_after_probe_and_cleanup(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(qualifier, "ROOT", tmp_path)
    scripts = tmp_path / "backend/scripts"
    scripts.mkdir(parents=True)
    for name in qualifier.FILES:
        (scripts / name).write_text("synthetic source")
    verify, probe = Mock(), Mock(return_value=result())
    monkeypatch.setattr(qualifier, "verify_inputs", verify)
    monkeypatch.setattr(qualifier, "probe", probe)
    monkeypatch.setattr(qualifier, "source_contract", lambda _: {"synthetic": True})
    path = tmp_path / "fast-document-migration-rehearsal.json"
    receipt = qualifier.qualify("sha256:" + "a" * 64, "b" * 40, "sha256:" + "c" * 64, path)
    assert receipt["checks"] == qualifier.CHECKS
    assert receipt["full_ci_qualified"] is False and receipt["owned_resources_removed"] is True
    assert json.loads(path.read_text()) == receipt
    assert verify.call_count == 2
    probe.assert_called_once()


def test_failed_probe_never_writes_passing_receipt(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(qualifier, "verify_inputs", Mock())
    monkeypatch.setattr(qualifier, "probe", Mock(side_effect=RuntimeError("cleanup failed")))
    path = tmp_path / "receipt.json"
    with pytest.raises(RuntimeError, match="cleanup failed"):
        qualifier.qualify("sha256:" + "a" * 64, "b" * 40, "sha256:" + "c" * 64, path)
    assert not path.exists()
