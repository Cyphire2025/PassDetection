import copy
import unittest

from image_runtime_policy import (
    BACKEND_PROCESSES,
    reviewed_process_command,
    validate_process_isolation,
)


class ProcessIsolationTests(unittest.TestCase):
    def setUp(self):
        self.services = {name: {"user": "1001:1001", "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"], "privileged": False,
            "command": reviewed_process_command(name)}
            for name in BACKEND_PROCESSES}

    def test_all_reviewed_processes(self):
        validate_process_isolation(self.services)

    def test_startup_cannot_replace_reviewed_code_or_append_shell_commands(self):
        for name in BACKEND_PROCESSES:
            for mutation in ({"entrypoint": ["python", "-c", "import ctypes"]},
                             {"entrypoint": []}, {"working_dir": "/run/gc-fcm"},
                             {"command": ["python", "-c", "import ctypes"]}):
                services = copy.deepcopy(self.services)
                services[name].update(mutation)
                with self.subTest(process=name, mutation=mutation), self.assertRaises(ValueError):
                    validate_process_isolation(services)
        for suffix in ("; python -c 'import ctypes'", " && /run/gc-fcm/helper", " $(/run/gc-fcm/helper)"):
            services = copy.deepcopy(self.services)
            services["worker"]["command"][2] += suffix
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                validate_process_isolation(services)
        self.services["worker"]["command"] = reviewed_process_command("worker", 8)
        validate_process_isolation(self.services)

    def test_each_process_rejects_each_privilege_escape(self):
        mutations = [{"user": "0"}, {"cap_drop": []}, {"cap_add": ["SYS_ADMIN"]},
            {"security_opt": []}, {"security_opt": ["no-new-privileges:true", "seccomp:unconfined"]},
            {"privileged": True}, {"pid": "host"}, {"ipc": "host"},
            {"devices": ["/dev/sda"]}, {"device_cgroup_rules": ["a *:* rwm"]},
            {"volumes": [{"type": "bind", "source": "/", "target": "/host"}]}]
        for name in BACKEND_PROCESSES:
            for mutation in mutations:
                with self.subTest(process=name, mutation=mutation):
                    services = copy.deepcopy(self.services)
                    services[name].update(mutation)
                    with self.assertRaises(ValueError):
                        validate_process_isolation(services)

    def test_credential_mount_must_be_exact_and_read_only(self):
        volume = {"type": "bind", "source": "/opt/global-connect-secrets/fcm",
                  "target": "/run/gc-fcm", "read_only": True}
        self.services["worker"]["volumes"] = [volume]
        validate_process_isolation(self.services)
        volume["read_only"] = False
        with self.assertRaises(ValueError):
            validate_process_isolation(self.services)

    def test_every_runtime_rejects_alternate_code_and_filesystem_overlays(self):
        mutations = [
            {"volumes": [{"type": "volume", "source": "other-code", "target": "/usr/local"}]},
            {"volumes": [{"type": "volume", "source": "other-code", "target": "/opt/venv"}]},
            {"volumes": [{"type": "volume", "source": "other-code", "target": "/app"}]},
            {"volumes": [{"type": "tmpfs", "target": "/usr/lib"}]},
            {"tmpfs": ["/app"]},
            {"volumes_from": ["external:unreviewed"]},
            {"configs": [{"source": "unreviewed", "target": "/app/app/main.py"}]},
            {"secrets": [{"source": "unreviewed", "target": "/usr/local/lib/python3.11/sitecustomize.py"}]},
        ]
        for name in BACKEND_PROCESSES:
            for mutation in mutations:
                with self.subTest(process=name, mutation=mutation):
                    services = copy.deepcopy(self.services)
                    services[name].update(mutation)
                    with self.assertRaises(ValueError):
                        validate_process_isolation(services)

    def test_every_runtime_rejects_environment_that_can_replace_scanned_code(self):
        for name in BACKEND_PROCESSES:
            for variable in ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "PYTHONPATH",
                             "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"):
                with self.subTest(process=name, variable=variable):
                    services = copy.deepcopy(self.services)
                    services[name]["environment"] = {variable: "/run/gc-fcm/unreviewed"}
                    with self.assertRaises(ValueError):
                        validate_process_isolation(services)

    def test_exact_confinement_excludes_unreviewed_custom_profiles(self):
        for name in BACKEND_PROCESSES:
            for option in ("seccomp:/tmp/allow-all.json", "apparmor:unreviewed-profile", "label:disable"):
                with self.subTest(process=name, option=option):
                    services = copy.deepcopy(self.services)
                    services[name]["security_opt"].append(option)
                    with self.assertRaises(ValueError):
                        validate_process_isolation(services)

    def test_storage_copy_retains_only_its_protected_evidence_mount(self):
        self.services["database-admin"]["environment"] = {"OBJECT_STORAGE_MIGRATION_DIRECTORY": "/protected/release"}
        safe = {"user": "0:0", "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                "restart": "no", "command": ["python", "scripts/copy_storage_snapshot.py"],
                "volumes": [{"type": "bind", "source": "/protected/release", "target": "/evidence",
                             "bind": {"create_host_path": False}}]}
        self.services["storage-copy"] = safe
        validate_process_isolation(self.services)
        for mutation in ({"cap_add": ["DAC_OVERRIDE"]}, {"command": ["sh"]}, {"entrypoint": ["sh"]},
                         {"restart": "always"}, {"security_opt": []}, {"privileged": True},
                         {"device_cgroup_rules": ["a *:* rwm"]},
                         {"tmpfs": ["/app"]}, {"volumes_from": ["external:unreviewed"]},
                         {"configs": [{"source": "unreviewed", "target": "/app/scripts/copy_storage_snapshot.py"}]},
                         {"secrets": [{"source": "unreviewed", "target": "/usr/local/lib/python3.11/sitecustomize.py"}]},
                         {"environment": {"PYTHONPATH": "/evidence"}},
                         {"environment": {"LD_PRELOAD": "/evidence/unreviewed.so"}},
                         {"volumes": []}, {"volumes": [{"type": "bind", "source": "/", "target": "/evidence",
                                                       "bind": {"create_host_path": False}}]}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.services["storage-copy"] = {**safe, **mutation}
                validate_process_isolation(self.services)


if __name__ == "__main__":
    unittest.main()
