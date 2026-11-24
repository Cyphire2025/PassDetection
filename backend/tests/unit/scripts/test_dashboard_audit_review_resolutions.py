"""Full-file coverage cannot silently close independent audit follow-ups."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[4] / "scripts/dashboard_audit_inventory.py"
SPEC = importlib.util.spec_from_file_location("dashboard_audit_resolution_controls", PATH)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


def _reviews(*, full_status="verified"):
    partial = {
        "path": "backend/example.py", "sha256": "a" * 64,
        "review_scope": "focused", "status": "needs-follow-up",
        "notes": "The final complete source read remains open.",
    }
    identity = inventory.review_record_digest(partial)
    full = {
        **partial, "review_scope": "full", "status": full_status,
        "resolves_partial_reviews": [{
            "ledger": "before-reviewed-files.json", "record_sha256": identity,
            "reason": "Read the remaining physical source and traced every retained branch.",
        }],
    }
    return {partial["path"]: [
        {**partial, "_ledger": "before-reviewed-files.json", "_record_digest": identity},
        {**full, "_ledger": "after-reviewed-files.json",
         "_record_digest": inventory.review_record_digest(full)},
    ]}


def test_resolution_preserves_the_exact_original_ledger_and_independent_full_followup():
    reviews = _reviews()
    records = reviews["backend/example.py"]
    architecture = {**records[0], "review_scope": "full",
                    "_ledger": "architecture-reviewed-files.json"}
    architecture["_record_digest"] = inventory.review_record_digest(architecture)
    records.append(architecture)
    original = json.loads(json.dumps(reviews))
    resolved = inventory.resolved_partial_reviews(reviews)
    assert resolved == {(records[0]["_ledger"], records[0]["_record_digest"])}
    assert (architecture["_ledger"], architecture["_record_digest"]) not in resolved
    assert reviews == original


def test_a_full_read_can_close_partial_depth_while_its_own_finding_remains_open():
    reviews = _reviews(full_status="needs-follow-up")
    resolved = inventory.resolved_partial_reviews(reviews)
    assert len(resolved) == 1
    assert reviews["backend/example.py"][1]["status"] == "needs-follow-up"


@pytest.mark.parametrize("change", ["hash", "path", "record", "ledger", "partial", "full-task", "reason"])
def test_invalid_resolution_cannot_hide_unreviewed_or_independently_open_work(change):
    reviews = _reviews()
    partial, full = reviews["backend/example.py"]
    reference = full["resolves_partial_reviews"][0]
    if change == "hash":
        full["sha256"] = "b" * 64
    elif change == "path":
        full["path"] = "backend/another.py"
    elif change == "record":
        reference["record_sha256"] = "b" * 64
    elif change == "ledger":
        reference["ledger"] = "different-reviewed-files.json"
    elif change == "partial":
        full["review_scope"] = "focused"
    elif change == "full-task":
        partial["review_scope"] = "full"
    elif change == "reason":
        reference["reason"] = "  "
    with pytest.raises(ValueError):
        inventory.resolved_partial_reviews(reviews)


def test_resolution_is_explicit_and_record_digest_does_not_depend_on_json_key_order():
    reviews = _reviews()
    partial, full = reviews["backend/example.py"]
    full.pop("resolves_partial_reviews")
    assert inventory.resolved_partial_reviews(reviews) == set()
    assert inventory.review_record_digest(partial) == inventory.review_record_digest(
        dict(reversed(list(partial.items())))
    )


@pytest.mark.parametrize(("metadata", "expected"), [
    ({"notes": "Exact source context."}, "Exact source context."),
    ({"notes": ["First context.", "Second context."]}, "First context. | Second context."),
    ({"notes": []}, ""),
    ({}, "Exact review record: context-reviewed-files.json"),
    ({"review_method": ["Physical read.", "Caller trace."]}, "Physical read. | Caller trace."),
    ({"notes": None, "review_method": "Physical read."}, "Physical read."),
    ({"notes": None}, "Exact review record: context-reviewed-files.json"),
])
def test_refresh_normalizes_display_notes_without_changing_original_record_digest(
    tmp_path, monkeypatch, metadata, expected,
):
    report = tmp_path / "audit"
    report.mkdir()
    source = tmp_path / "backend/example.py"
    source.parent.mkdir()
    source.write_text("pass\n", encoding="utf-8")
    record = {"path": "backend/example.py", "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "review_scope": "full", "status": "verified", **metadata}
    ledger = report / "context-reviewed-files.json"
    original = json.dumps([record]).encode("utf-8")
    ledger.write_bytes(original)
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory, "REPORT", report)
    monkeypatch.setattr(inventory.subprocess, "check_output", lambda *_args, **_kwargs: b"backend/example.py\0")
    resolve = inventory.resolved_partial_reviews
    seen = []

    def capture(reviews):
        seen.extend(reviews[record["path"]])
        return resolve(reviews)

    monkeypatch.setattr(inventory, "resolved_partial_reviews", capture)
    summary = inventory.refresh([], "reviewed", "test", "")
    with (report / "file-inventory.csv").open(encoding="utf-8", newline="") as stream:
        row, = csv.DictReader(stream)
    assert row["notes"] == expected
    assert row["review_scope"] == "full" and row["status"] == "verified"
    assert seen[0]["_record_digest"] == inventory.review_record_digest(record)
    assert ledger.read_bytes() == original
    assert summary["files"] == 1


@pytest.mark.parametrize("notes", [17, {}, ["Context", None], [["Nested context"]]])
def test_invalid_notes_fail_before_replacing_the_inventory(tmp_path, monkeypatch, notes):
    report = tmp_path / "audit"
    report.mkdir()
    original_inventory = b"existing inventory must remain intact\n"
    (report / "file-inventory.csv").write_bytes(original_inventory)
    (report / "invalid-reviewed-files.json").write_text(json.dumps([{
        "path": "backend/example.py", "sha256": "a" * 64, "notes": notes,
    }]), encoding="utf-8")
    monkeypatch.setattr(inventory, "REPORT", report)
    monkeypatch.setattr(inventory, "ROOT", tmp_path)
    monkeypatch.setattr(inventory.subprocess, "check_output", lambda *_args, **_kwargs: b"")
    with pytest.raises(ValueError, match="Review notes"):
        inventory.refresh([], "reviewed", "test", "")
    assert (report / "file-inventory.csv").read_bytes() == original_inventory


def test_list_notes_stay_part_of_the_exact_partial_resolution_identity():
    reviews = _reviews()
    partial, full = reviews["backend/example.py"]
    partial["notes"] = ["First retained note.", "Second retained note."]
    original = {key: value for key, value in partial.items() if not key.startswith("_")}
    partial["_record_digest"] = inventory.review_record_digest(original)
    full["resolves_partial_reviews"][0]["record_sha256"] = partial["_record_digest"]
    assert inventory.resolved_partial_reviews(reviews) == {(partial["_ledger"], partial["_record_digest"])}
    full["resolves_partial_reviews"][0]["record_sha256"] = inventory.review_record_digest({
        **original, "notes": " | ".join(original["notes"]),
    })
    with pytest.raises(ValueError, match="missing or changed"):
        inventory.resolved_partial_reviews(reviews)


def test_legacy_contact_retirement_keeps_each_original_hash_and_physical_line_count(tmp_path, monkeypatch):
    records = [
        {"path": "frontend/features/upload/components/upload-contact-verification.tsx", "sha256": "a" * 64, "physical_lines": 185},
        {"path": "frontend/features/upload/components/upload-contact-verification.test.tsx", "sha256": "b" * 64, "physical_lines": 123},
    ]
    manifest = tmp_path / "legacy-contact-retirement-manifest.json"
    original = json.dumps({"original_files": records}).encode("utf-8")
    manifest.write_bytes(original)
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    history = inventory.retired_source_history()
    for record in records:
        row = history[record["path"]]
        assert row["sha256"] == record["sha256"] and row["lines"] == record["physical_lines"]
        assert row["status"] == "removed-in-working-tree" and row["review_scope"] == "retired"
    assert manifest.read_bytes() == original


@pytest.mark.parametrize("change", ["path", "traversal", "hash", "conflict", "source"])
def test_new_retirement_manifest_preserves_path_hash_conflict_and_source_validation(tmp_path, monkeypatch, change):
    record = {"path": "frontend/features/upload/components/retired.tsx", "sha256": "a" * 64, "physical_lines": 185}
    if change == "path":
        record["path"] = "backend/unrelated.py"
    elif change == "traversal":
        record["path"] = "frontend/features/../../outside.tsx"
    elif change == "hash":
        record["sha256"] = "not-a-digest"
    elif change == "source":
        record["source"] = "Source does not match the declared digest."
    elif change == "conflict":
        (tmp_path / "legacy-upload-retired-files.json").write_text(json.dumps({
            "retired": [{**record, "sha256": "b" * 64}],
        }), encoding="utf-8")
    (tmp_path / "legacy-contact-retirement-manifest.json").write_text(json.dumps({"original_files": [record]}), encoding="utf-8")
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    with pytest.raises(ValueError):
        inventory.retired_source_history()


@pytest.mark.parametrize("line_metadata", [
    {"physical_lines": -1}, {"physical_lines": True}, {"physical_lines": "185"},
    {"physicalLines": 184, "physical_lines": 185},
])
def test_retirement_rejects_invalid_or_conflicting_line_metadata(tmp_path, monkeypatch, line_metadata):
    record = {"path": "frontend/features/upload/components/retired.tsx", "sha256": "a" * 64, **line_metadata}
    (tmp_path / "legacy-contact-retirement-manifest.json").write_text(json.dumps({"original_files": [record]}), encoding="utf-8")
    monkeypatch.setattr(inventory, "REPORT", tmp_path)
    with pytest.raises(ValueError, match="physical line"):
        inventory.retired_source_history()
