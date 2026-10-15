"""Migration rehearsal cleanup and input guards, without Docker or live data."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from qa import qualify_document_migration as qualifier


def container(*, database: bool, started: bool = True) -> dict:
    tmpfs = qualifier.DATABASE_TMPFS if database else qualifier.CLIENT_TMPFS
    return {"HostConfig": {"Tmpfs": dict(tmpfs)}, "Mounts": [
        {"Type": "tmpfs", "Destination": path, "RW": True, "Source": ""}
        for path in tmpfs
    ] if started else []}


class MigrationOwnershipTests(unittest.TestCase):
    def test_only_reviewed_image_volume_is_overridden_by_disposable_tmpfs(self):
        qualifier.verify_image_volumes({"Config": {"Volumes": None}}, database=False)
        qualifier.verify_image_volumes({"Config": {"Volumes": {}}}, database=False)
        qualifier.verify_image_volumes({"Config": {"Volumes": {"/var/lib/postgresql/data": {}}}}, database=True)
        for database, volumes in ((False, {"/uploads": {}}), (True, {"/var/lib/postgresql": {}}),
                                  (True, {"/var/lib/postgresql/data": {}, "/other": {}}), (False, [])):
            with self.subTest(database=database, volumes=volumes), self.assertRaisesRegex(ValueError, "image_volume"):
                qualifier.verify_image_volumes({"Config": {"Volumes": volumes}}, database=database)

    def test_owned_started_and_unstarted_tmpfs_containers_can_be_cleaned(self):
        for database in (False, True):
            for started in (False, True):
                qualifier.verify_cleanup_mounts(container(database=database, started=started), database=database)

    def test_mount_type_destination_intent_and_readonly_changes_are_rejected(self):
        mutations = [
            lambda row: row["Mounts"][0].update(Type="volume", Name="production-data"),
            lambda row: row["Mounts"][0].update(Type="bind", Source="/production"),
            lambda row: row["Mounts"][0].update(Destination="/tmp"),
            lambda row: row["Mounts"][0].update(RW=False),
            lambda row: row["Mounts"].append(copy.deepcopy(row["Mounts"][0])),
            lambda row: row["HostConfig"].update(Tmpfs=qualifier.CLIENT_TMPFS),
            lambda row: row["HostConfig"].update(Binds=["live:/data"]),
            lambda row: row["HostConfig"].update(VolumesFrom=["live"]),
            lambda row: row["HostConfig"].update(Mounts=[{"Type": "volume", "Source": "live"}]),
        ]
        for index, mutate in enumerate(mutations):
            row = container(database=True)
            mutate(row)
            with self.subTest(index=index), self.assertRaisesRegex(RuntimeError, "cleanup_mounts_changed"):
                qualifier.verify_cleanup_mounts(row, database=True)

    def test_unknown_volume_rejected_before_any_probe_can_start(self):
        image, postgres, revision = "sha256:" + "a" * 64, "sha256:" + "b" * 64, "c" * 40
        calls = []
        def command(*args):
            calls.append(args)
            if args[:3] == ("docker", "context", "inspect"):
                return '[{"Endpoints":{"docker":{"Host":"unix:///var/run/docker.sock"}}}]'
            return revision if "rev-parse" in args else ""
        metadata = {"Id": image, "Config": {"Labels": {"org.opencontainers.image.revision": revision},
                                               "Volumes": {"/unreviewed": {}}}}
        with patch.object(qualifier.os, "name", "posix"), patch.dict(qualifier.os.environ, {"DOCKER_HOST": ""}), \
             patch.object(qualifier, "command", side_effect=command), patch.object(qualifier, "inspect", return_value=metadata), \
             self.assertRaisesRegex(ValueError, "image_volume"):
            qualifier.verify_inputs(image, revision, postgres)
        self.assertFalse(any("create" in call for call in calls))

    def test_timed_out_create_is_discovered_and_removed_only_with_exact_intent(self):
        owner = "pd-document-migration-" + "d" * 32
        row = {**container(database=True, started=False), "Id": "e" * 64, "Name": "/" + owner + "-db",
               "Config": {"Labels": {qualifier.LABEL: owner}}}
        row["HostConfig"]["NetworkMode"] = "none"
        calls = []
        def command(*args):
            calls.append(args)
            if args[:2] == ("docker", "create"):
                raise TimeoutError("response lost after create")
            return row["Id"] if args[:3] == ("docker", "ps", "-aq") else ""
        with patch.object(qualifier.uuid, "uuid4", return_value=SimpleNamespace(hex="d" * 32)), \
             patch.object(qualifier, "guard"), patch.object(qualifier, "command", side_effect=command), \
             patch.object(qualifier, "inspect", return_value=row), self.assertRaises(TimeoutError):
            qualifier.probe("image", "postgres", "hash", {})
        self.assertIn(("docker", "rm", "-f", "-v", row["Id"]), calls)

    def test_changed_cleanup_ownership_is_never_removed(self):
        row = {**container(database=True), "Id": "e" * 64, "Name": "/unexpected", "Config": {"Labels": {}}}
        row["HostConfig"]["NetworkMode"] = "none"
        command = Mock(side_effect=lambda *args: row["Id"] if args[:3] == ("docker", "ps", "-aq") else "")
        with patch.object(qualifier, "guard", side_effect=RuntimeError("stopped before create")), \
             patch.object(qualifier, "command", command), patch.object(qualifier, "inspect", return_value=row), \
             self.assertRaisesRegex(RuntimeError, "cleanup_ownership_changed"):
            qualifier.probe("image", "postgres", "hash", {})
        self.assertFalse(any(call.args[:2] == ("docker", "rm") for call in command.call_args_list))

    def test_contract_drift_after_successful_probe_never_writes_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            output.parent.chmod(0o700)
            with patch.object(qualifier, "verify_inputs"), patch.object(qualifier, "probe"), \
                 patch.object(qualifier, "source_contract", side_effect=[{"contract": "before"}, {"contract": "after"}]), \
                 patch.object(qualifier, "write_exclusive") as write, \
                 self.assertRaisesRegex(ValueError, "qualification_source_changed"):
                qualifier.qualify("image", "revision", "postgres", output)
            write.assert_not_called()
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
