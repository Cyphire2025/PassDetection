"""Exercise current release sequencing, backup failure and role cutover gates.

Docker is simulated here; PostgreSQL privilege behavior is checked separately
by backend/scripts/qualify_database_roles.py against a real isolated database.
"""

import copy
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from release_current import CurrentRelease
from release_manifest import ROOT, load_release_manifest
from release_reliability import DUMP_COMMAND
from release_traveller_whatsapp import ReleaseError
from storage_release import STORAGE_IMAGE
from test_release_reliability import DATABASE_ENV, RecoveryDocker
from test_release_traveller_whatsapp import NEW_WORKER, REVISION

MAINTAINED_STORAGE_ID = "sha256:" + "5" * 64
LEGACY_STORAGE_ID = "sha256:" + "6" * 64
LEGACY_STORAGE_VOLUME = "existing_minio_data"
APP_STORAGE_ENV = {
    "S3_ENDPOINT_URL": "http://minio:9000", "S3_PUBLIC_ENDPOINT_URL": "https://files.example.test",
    "S3_BUCKET_NAME": "existing-passports", "S3_ACCESS_KEY_ID": "existing-app",
    "S3_SECRET_ACCESS_KEY": "existing-app-secret",
}
LEGACY_STORAGE_ENV = {"MINIO_ROOT_USER": "legacy-admin", "MINIO_ROOT_PASSWORD": "legacy-admin-secret"}


class CurrentDocker(RecoveryDocker):
    def __init__(self, root):
        super().__init__(root)
        self.expected_schema = self.schema = load_release_manifest()["schema_revision"]
        self.command_environment = {}
        self.fail_provision = False
        self.fail_copy = False
        self.copy_timeout = False
        self.copy_stop_failure = False
        self.fail_stage = False
        self.unclean_writer = None
        self.storage_space = "Filesystem 1024-blocks Used Available Capacity Mounted on\nsynthetic 10000000 1000000 9000000 10% /data\n"
        self.copy_report = {
            "version": 1, "bucket": APP_STORAGE_ENV["S3_BUCKET_NAME"],
            "every_copied_body_sha256_verified": True, "source_deleted": False,
            "versions_including_delete_markers": 7, "source_endpoint": "http://minio:9000",
            "destination_endpoint": "http://storage-stage:9000",
        }
        self.volumes = {LEGACY_STORAGE_VOLUME}
        self.images[STORAGE_IMAGE] = {"Id": MAINTAINED_STORAGE_ID, "Config": {"Env": []}}
        self.images[MAINTAINED_STORAGE_ID] = self.images[STORAGE_IMAGE]
        self.containers["minio"] = self.make_container("minio", LEGACY_STORAGE_ID)
        self.containers["minio"]["Config"].update(
            Image="minio/minio:RELEASE.synthetic", Env=[f"{key}={value}" for key, value in LEGACY_STORAGE_ENV.items()],
        )
        self.containers["minio"]["Mounts"] = [{"Type": "volume", "Name": LEGACY_STORAGE_VOLUME, "Destination": "/data"}]
        self.containers["backend"]["Config"]["Env"].extend(f"{key}={value}" for key, value in APP_STORAGE_ENV.items())

    def environment(self):
        return {
            key: value.strip().strip("\"'") for key, value in (
                line.split("=", 1) for line in (self.root / ".env").read_text().splitlines()
                if "=" in line and not line.lstrip().startswith("#")
            )
        }

    def config(self):
        config = super().config()
        values = self.environment()
        manifest = load_release_manifest()
        for name in (*manifest["worker_nodes"], "email-beat", "backend"):
            service = config["services"][name]
            service["environment"].update(
                POSTGRES_DB=DATABASE_ENV["POSTGRES_DB"], POSTGRES_HOST="db", POSTGRES_PORT="5432",
                POSTGRES_USER=values["POSTGRES_RUNTIME_USER"],
                POSTGRES_PASSWORD=values["POSTGRES_RUNTIME_PASSWORD"],
                EXPECTED_DATABASE_SCHEMA_REVISION=self.command_environment.get(
                    "EXPECTED_DATABASE_SCHEMA_REVISION", values["EXPECTED_DATABASE_SCHEMA_REVISION"]
                ),
            )
            if name in manifest["worker_nodes"]:
                service["command"] = f"celery worker --hostname={manifest['worker_nodes'][name]}@%h"
        config["services"]["database-admin"] = {
            "image": "passdetection-backend", "networks": {"passdetection-net": None},
            "environment": {**values, **DATABASE_ENV, "POSTGRES_HOST": "db", "POSTGRES_PORT": "5432"},
        }
        config["services"]["database-migrate"] = {
            "image": "passdetection-backend", "networks": {"passdetection-net": None}, "environment": {
                **DATABASE_ENV, "POSTGRES_USER": values["POSTGRES_MIGRATION_USER"],
                "POSTGRES_PASSWORD": values["POSTGRES_MIGRATION_PASSWORD"],
                "POSTGRES_HOST": "db", "POSTGRES_PORT": "5432",
            },
        }
        for name in ("minio", "storage-stage"):
            config["services"][name] = {
                "image": STORAGE_IMAGE, "networks": {"passdetection-net": None},
                "volumes": [
                    {"type": "volume", "source": "object_storage_data", "target": "/data"},
                    {"type": "bind", "source": values["OBJECT_STORAGE_IDENTITY_FILE"],
                     "target": "/run/secrets/s3.json", "read_only": True},
                ],
            }
        config["services"]["storage-copy"] = {"image": "passdetection-backend", "networks": {"passdetection-net": None}, "environment": {
            "S3_BUCKET_NAME": values["S3_BUCKET_NAME"],
            "STORAGE_SOURCE_ENDPOINT": "http://minio:9000", "STORAGE_DESTINATION_ENDPOINT": "http://storage-stage:9000",
        }}
        config["volumes"] = {"object_storage_data": {"name": values["OBJECT_STORAGE_DATA_VOLUME"]}}
        return config

    def run(self, args, **kwargs):
        args = list(args)
        self.command_environment = kwargs.get("env", {})
        if args[:2] == ["docker", "ps"] and any(value.startswith("name=^/") for value in args):
            self.calls.append(args)
            name = next(value[len("name=^"):-1] for value in args if value.startswith("name=^/"))
            matches = [value["Id"] for value in self.containers.values() if value.get("Name") == name]
            return subprocess.CompletedProcess(args, 0, stdout="\n".join(matches), stderr="")
        if args[:2] == ["docker", "stop"]:
            self.calls.append(args)
            assert args[2:4] == ["--time", "30"]
            container = next(value for value in self.containers.values() if value["Id"] == args[-1])
            if not self.copy_stop_failure:
                container["State"]["Running"] = False
            return subprocess.CompletedProcess(args, int(self.copy_stop_failure), stdout="", stderr="")
        if args[:2] == ["docker", "pull"]:
            assert args[-1] == STORAGE_IMAGE
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="immutable storage image available", stderr="")
        if args[:2] == ["docker", "start"]:
            self.calls.append(args)
            for identifier in args[2:]:
                container = next(value for value in self.containers.values() if value["Id"] == identifier)
                container["State"].update(Running=True, ExitCode=0)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:2] == ["docker", "exec"] and args[2] == self.containers["nginx"]["Id"]:
            assert args[3:] in (["nginx", "-t"], ["nginx", "-s", "reload"])
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if "config" in args and "--format" in args:
            self.calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(self.config()), stderr="")
        if "scripts/provision_database_roles.py" in args:
            self.calls.append(list(args))
            _, pin_path = self.compose_command(args)
            pins = json.loads(pin_path.read_text())["services"]
            assert pins["database-admin"]["image"] == NEW_WORKER
            return subprocess.CompletedProcess(args, int(self.fail_provision), stdout="", stderr="")
        if args[:2] == ["docker", "compose"]:
            tail, pin_path = self.compose_command(args)
            if tail == ["exec", "-T", "storage-stage", "df", "-Pk", "/data"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout=self.storage_space, stderr="")
            if tail[:1] == ["stop"]:
                self.calls.append(args)
                for name in tail[3:]:
                    self.containers[name]["State"].update(Running=False, ExitCode=137 if name == self.unclean_writer else 0)
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if tail[:1] == ["up"] and tail[-1] in {"storage-stage", "minio"}:
                self.calls.append(args)
                name = tail[-1]
                if name == "storage-stage" and self.fail_stage:
                    return subprocess.CompletedProcess(args, 1, stdout="", stderr="")
                values = self.environment()
                if name == "minio":
                    assert not self.containers["storage-stage"]["State"]["Running"]
                    assert Path(values["OBJECT_STORAGE_CUTOVER_PROOF"]).is_file()
                container = self.make_container(name, MAINTAINED_STORAGE_ID)
                if name == "minio":
                    container["Id"] = "container-maintained-minio"
                container["Config"]["Image"] = STORAGE_IMAGE
                container["State"]["Health"] = {"Status": "healthy"}
                container["Mounts"] = [
                    {"Type": "volume", "Name": values["OBJECT_STORAGE_DATA_VOLUME"], "Destination": "/data"},
                    {"Type": "bind", "Source": values["OBJECT_STORAGE_IDENTITY_FILE"],
                     "Destination": "/run/secrets/s3.json", "RW": False},
                ]
                self.volumes.add(values["OBJECT_STORAGE_DATA_VOLUME"])
                self.containers[name] = container
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if tail[:1] == ["run"] and "storage-copy" in tail:
                self.calls.append(args)
                pins = json.loads(pin_path.read_text())["services"]
                assert pins["storage-copy"]["image"] == NEW_WORKER
                assert f"STORAGE_AVAILABLE_BYTES={int(self.storage_space.splitlines()[-1].split()[3]) * 1024}" in tail
                assert all(not self.containers[name]["State"]["Running"] for name in (*load_release_manifest()["worker_nodes"], "email-beat", "backend"))
                assert self.containers["minio"]["Image"] == LEGACY_STORAGE_ID
                assert self.containers["storage-stage"]["State"]["Running"]
                checkpoint = json.loads((self.root / "tmp/current-release/storage-writer-fence.json").read_text())
                claim = checkpoint["copy"]
                assert tail[tail.index("--name") + 1] == claim["name"]
                assert "passdetection.storage-copy-token=" + claim["token"] in tail
                if self.copy_timeout:
                    container = self.make_container("storage-copy", NEW_WORKER)
                    container["Name"] = "/" + claim["name"]
                    container["Config"].update(
                        Cmd=["python", "scripts/copy_storage_snapshot.py"],
                        Env=[f"{key}={value}" for key, value in claim["environment"].items()],
                    )
                    container["Config"]["Labels"]["passdetection.storage-copy-token"] = claim["token"]
                    container["Mounts"] = [{"Type": "bind", "Source": claim["evidence_directory"], "Destination": "/evidence"}]
                    self.containers["storage-copy"] = container
                    raise subprocess.TimeoutExpired(args, kwargs["timeout"])
                return subprocess.CompletedProcess(args, int(self.fail_copy), stdout=json.dumps(self.copy_report), stderr="")
        return super().run(args, **kwargs)


class CurrentReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in (".env.example", "docker-compose.yml", "backend/app/core/config/release_manifest.json"):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        self.original = "EXPECTED_DATABASE_SCHEMA_REVISION=" + load_release_manifest()["schema_revision"] + "\nORIGINAL=preserve-me\n"
        self.original += "".join(f"{key}={value}\n" for key, value in {**APP_STORAGE_ENV, **LEGACY_STORAGE_ENV}.items())
        (self.root / ".env").write_text(self.original)
        manifest = load_release_manifest()
        workers = (*manifest["worker_nodes"], "email-beat")
        for name, value in (("WORKERS", workers), ("ACTIVATED", (*workers, "backend", "frontend"))):
            patcher = patch("test_release_traveller_whatsapp." + name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fake = CurrentDocker(self.root)
        patcher = patch("release_traveller_whatsapp.subprocess.run", side_effect=self.fake.run)
        patcher.start()
        self.addCleanup(patcher.stop)
        capture = redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.release = CurrentRelease(REVISION, self.root)

    def test_backup_precedes_role_provision_and_migration_then_all_eight_workers(self):
        self.release.prepare()
        self.release.activate()
        calls = self.fake.calls
        provision = self.fake.commands("scripts/provision_database_roles.py")[0]
        self.assertLess(calls.index(self.fake.commands("cp")[0]), calls.index(provision))
        self.assertLess(calls.index(provision), calls.index(self.fake.commands("upgrade")[0]))
        self.assertIn("database-admin", self.fake.commands("current")[0])
        self.assertIn("database-migrate", self.fake.commands("upgrade")[0])
        self.assertTrue(any("ecr-worker" in call for call in self.fake.commands("up")))
        self.assertEqual((self.release.directory / f"{REVISION}.env.backup").read_text(), self.original)
        self.assertFalse(any(set(call) & {"down", "prune", "downgrade", "purge"} for call in calls))

    def test_bad_backup_never_provisions_or_activates(self):
        self.release.prepare()
        self.fake.backup_failure = "decode"
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertFalse(self.fake.commands("scripts/provision_database_roles.py"))
        self.assertFalse(self.fake.commands("up"))
        self.assertFalse(self.fake.commands("stop"))

    def test_failed_provision_never_migrates_or_restarts(self):
        self.release.prepare()
        self.fake.fail_provision = True
        with self.assertRaises(ReleaseError):
            self.release.activate()
        self.assertTrue(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))
        self.assertFalse(self.fake.commands("stop"))

    def test_actual_stale_env_is_not_masked_by_candidate_override(self):
        self.release.prepare()
        (self.root / ".env").write_text((self.root / ".env").read_text().replace(
            load_release_manifest()["schema_revision"], "0093_phone_welcome"
        ))
        with self.assertRaisesRegex(ValueError, "configured schema"):
            self.release.activate()
        self.assertFalse(self.fake.commands("upgrade"))
        self.assertFalse(self.fake.commands("up"))

    def test_prepare_rejects_invalid_live_project_before_changing_environment(self):
        original = copy.deepcopy(self.fake.containers["backend"])
        for invalid in ("stopped", "wrong-service", "wrong-directory", "missing-project"):
            with self.subTest(invalid=invalid):
                backend = copy.deepcopy(original)
                if invalid == "stopped":
                    backend["State"]["Running"] = False
                elif invalid == "wrong-service":
                    backend["Config"]["Labels"]["com.docker.compose.service"] = "other"
                elif invalid == "wrong-directory":
                    backend["Config"]["Labels"]["com.docker.compose.project.working_dir"] = str(self.root / "other")
                else:
                    backend["Config"]["Labels"].pop("com.docker.compose.project")
                self.fake.containers["backend"] = backend
                with self.assertRaises(ReleaseError):
                    self.release.prepare()
                self.assertEqual((self.root / ".env").read_text(), self.original)
                self.assertFalse(self.release.directory.exists())
        self.assertFalse(self.fake.commands("build"))
        self.assertFalse(self.fake.commands(DUMP_COMMAND))

    def test_prepare_rejects_live_database_mismatch_before_credential_generation(self):
        original = copy.deepcopy(self.fake.containers["backend"])
        for key, value in (
            ("POSTGRES_HOST", "other-production-database"),
            ("POSTGRES_PORT", "5433"),
            ("POSTGRES_DB", "other-database"),
            ("POSTGRES_PORT", None),
        ):
            with self.subTest(key=key, value=value):
                backend = copy.deepcopy(original)
                backend["Config"]["Env"] = [
                    entry for entry in backend["Config"]["Env"] if not entry.startswith(key + "=")
                ]
                if value is not None:
                    backend["Config"]["Env"].append(f"{key}={value}")
                self.fake.containers["backend"] = backend
                with self.assertRaisesRegex(ReleaseError, "Live backend database identity"):
                    self.release.prepare()
                self.assertEqual((self.root / ".env").read_text(), self.original)
                self.assertFalse(self.release.directory.exists())
        self.assertFalse(self.fake.commands("build"))

    def test_prepare_rejects_unverified_database_network_before_changing_environment(self):
        original = copy.deepcopy(self.fake.containers["backend"])
        network = f"{self.fake.project}_passdetection-net"
        for invalid in ("missing-inspection", "different-network-id", "hostname-override"):
            with self.subTest(invalid=invalid):
                backend = copy.deepcopy(original)
                if invalid == "missing-inspection":
                    backend.pop("NetworkSettings")
                elif invalid == "different-network-id":
                    backend["NetworkSettings"]["Networks"][network]["NetworkID"] = "other-network"
                else:
                    backend["HostConfig"] = {"ExtraHosts": ["db:192.0.2.9"]}
                self.fake.containers["backend"] = backend
                with self.assertRaises(ReleaseError):
                    self.release.prepare()
                self.assertEqual((self.root / ".env").read_text(), self.original)
                self.assertFalse(self.release.directory.exists())

    def test_maintenance_target_drift_prevents_backup_provision_and_restart(self):
        self.release.prepare()
        prepared = (self.root / ".env").read_text()
        original_config = self.fake.config
        for service in ("database-admin", "database-migrate"):
            for field in ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB", "network"):
                with self.subTest(service=service, field=field):
                    def wrong_target():
                        config = original_config()
                        if field == "network":
                            config["services"][service]["networks"] = {"other-network": None}
                        else:
                            config["services"][service]["environment"][field] = "another-target"
                        return config

                    self.fake.config = wrong_target
                    # Exercise the target gate directly as well as activation:
                    # the fingerprint check independently rejects config drift.
                    with self.assertRaises(ReleaseError):
                        self.release._database_container(wrong_target())
                    with self.assertRaises(ReleaseError):
                        self.release.activate()
                    self.assertEqual((self.root / ".env").read_text(), prepared)
        self.assertFalse(self.fake.commands(DUMP_COMMAND))
        self.assertFalse(self.fake.commands("scripts/provision_database_roles.py"))
        self.assertFalse(self.fake.commands("up"))


if __name__ == "__main__":
    unittest.main()
