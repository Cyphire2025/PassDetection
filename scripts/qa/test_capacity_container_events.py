"""Historical OOM counters may be nonzero; new failures must never pass."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capacity_container_events import REQUIRED, capture, cgroup_for, gates, parse_events


class ContainerEventTests(unittest.TestCase):
    def setUp(self):
        self.before = {"containers": {service: {"id": service, "started_at": "initial",
            "restarts": 0, "oom_killed": False, "events": {"oom": 0, "oom_kill": 0}}
            for service in REQUIRED}}
        self.before["containers"]["nginx"].update(oom_killed=True,
            events={"oom": 151, "oom_kill": 3, "oom_group_kill": 0})
        self.after = copy.deepcopy(self.before)

    def test_existing_nginx_events_allow_an_unchanged_qualified_window(self):
        self.assertEqual(gates(self.before, self.after), [])

    def test_any_service_increment_fails_even_when_backend_is_healthy(self):
        for service, event in (("nginx", "oom_kill"), ("clamav", "oom"), ("worker", "oom_kill")):
            current = copy.deepcopy(self.after)
            current["containers"][service]["events"][event] += 1
            self.assertIn(f"containers:{service}:{event}_during_workload", gates(self.before, current))

    def test_restart_or_replacement_cannot_reset_oom_evidence(self):
        self.after["containers"]["nginx"].update(id="replacement", restarts=1,
            started_at="new", events={"oom": 0, "oom_kill": 0, "oom_group_kill": 0})
        failures = gates(self.before, self.after)
        self.assertIn("containers:nginx:restarted_or_replaced", failures)
        self.assertIn("containers:nginx:invalid_oom_evidence", failures)

    def test_missing_snapshot_container_or_counter_fails(self):
        self.assertEqual(gates(self.before, None), ["containers:missing_oom_evidence"])
        del self.after["containers"]["nginx"]["events"]["oom_kill"]
        self.assertIn("containers:nginx:missing_oom_evidence", gates(self.before, self.after))
        del self.after["containers"]["nginx"]
        self.assertEqual(gates(self.before, self.after), ["containers:inventory_changed_or_incomplete"])

    def test_event_parser_rejects_missing_duplicate_negative_and_nonnumeric(self):
        self.assertEqual(parse_events("oom 151\noom_kill 3\n"), {"oom": 151, "oom_kill": 3})
        for raw in ("oom 0", "oom -1\noom_kill 0", "oom 0\noom 1\noom_kill 0", "oom true\noom_kill 0"):
            with self.assertRaises(ValueError):
                parse_events(raw)

    def test_local_kernel_path_must_name_exact_container(self):
        identifier = "a" * 64
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc, cgroups = root / "proc", root / "cgroups"
            (proc / "123").mkdir(parents=True)
            expected = cgroups / "system.slice" / f"docker-{identifier}.scope"
            expected.mkdir(parents=True)
            entry = proc / "123" / "cgroup"
            entry.write_text(f"0::/system.slice/docker-{identifier}.scope\n")
            self.assertEqual(cgroup_for(identifier, 123, proc, cgroups), expected.resolve())
            for value in ("0::/\n", f"0::/../../{identifier}\n", f"1:memory:/{identifier}\n",
                          f"0::/system.slice/docker-{'b' * 64}.scope\n"):
                entry.write_text(value)
                with self.assertRaises(ValueError):
                    cgroup_for(identifier, 123, proc, cgroups)

    def test_capture_requires_local_daemon_exact_project_root_and_full_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            proc, cgroups = root / "proc", root / "cgroups"
            identities = {}
            for index, service in enumerate(sorted(REQUIRED), 1):
                identifier = format(index, "064x")
                (proc / str(index)).mkdir(parents=True)
                (proc / str(index) / "cgroup").write_text(f"0::/docker/{identifier}\n")
                directory = cgroups / "docker" / identifier
                directory.mkdir(parents=True)
                (directory / "memory.events").write_text("oom 0\noom_kill 0\n")
                identities[identifier] = {"id": identifier, "service": service,
                    "project": "passdetection-qualification", "root": str(root), "oneoff": "False",
                    "state": {"Running": True, "Pid": index, "StartedAt": "retained", "OOMKilled": False},
                    "restarts": 0}
            calls = []

            def run(*args):
                calls.append(args)
                if args[:3] == ("docker", "context", "inspect"):
                    return "unix:///var/run/docker.sock"
                if args[:2] == ("docker", "ps"):
                    return "\n".join(identities)
                if args[:2] == ("docker", "inspect"):
                    return json.dumps(identities[args[-1]])
                self.fail("A read-only snapshot issued an unexpected command")

            with patch("capacity_container_events.sys.platform", "linux"), patch.dict(
                "capacity_container_events.os.environ", {"DOCKER_HOST": "", "DOCKER_CONTEXT": ""}
            ):
                snapshot = capture(root, run=run, proc=proc, cgroups=cgroups)
                self.assertEqual(set(snapshot["containers"]), REQUIRED)
                self.assertEqual(gates(snapshot, snapshot), [])
                first = next(iter(identities.values()))
                for field, value in (("project", "production"), ("root", str(root / "other")),
                                     ("oneoff", "True")):
                    old, first[field] = first[field], value
                    with self.assertRaises(ValueError):
                        capture(root, run=run, proc=proc, cgroups=cgroups)
                    first[field] = old
                with patch.dict("capacity_container_events.os.environ", {"DOCKER_HOST": "tcp://remote"}):
                    before = len(calls)
                    with self.assertRaises(ValueError):
                        capture(root, run=run, proc=proc, cgroups=cgroups)
                    self.assertEqual(len(calls), before)


if __name__ == "__main__":
    unittest.main()
