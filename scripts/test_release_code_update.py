"""Safety contracts and failure ordering for same-schema web promotion."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from release_code_update import (
    CORE_CAPABILITIES, WEB, CodeUpdate, ReleaseError, task_contract,
    validate_capacity, validate_readiness, web_configuration,
)

REVISION = "b" * 40
PREVIOUS = "a" * 40
MIB = 1024**2
NGINX = "events {}\nhttp { upstream backend { server backend:8000; keepalive 128; }\nupstream frontend { server frontend:3000; keepalive 32; } }\n"


class Scenario(CodeUpdate):
    """Small fake Docker host; exercises real transition/recovery orchestration."""
    def __init__(self, root: Path, failure: str) -> None:
        super().__init__(REVISION, root, root / "signed.json")
        self.failure = failure
        self.failed = False
        self.events: list[str] = []
        self.items = {name: {"Id": f"old-{name}", "Image": f"old-image-{name}", "State": {"Running": True},
                             "Config": {"Hostname": name}} for name in self.activated_services}
        self.stages: dict[str, dict] = {}
        self.compose = ["docker", "compose", "-p", "synthetic"]

    def prepare(self) -> dict:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.original_env.write_text("APP_REVISION=" + PREVIOUS + "\n")
        self.record = {"phase": "prepared", "previous_revision": PREVIOUS, "original_recreated": False,
                       "original": {name: {"id": item["Id"], "image": item["Image"]} for name, item in self.items.items()},
                       "images": {name: f"new-image-{name}" for name in self.items}, "candidates": {}}
        return {}

    def trigger(self, point: str) -> None:
        if self.failure == point and not self.failed:
            self.failed = True
            raise ReleaseError("injected " + point)

    def save(self, phase: str) -> None:
        self.record["phase"] = phase
        self.events.append(phase)

    def verify_binding(self) -> None:
        pass

    def require_current_main(self) -> None:
        pass

    def unchanged_infrastructure(self) -> None:
        self.events.append("infra-verified")

    def pause_workers(self) -> None:
        self.events.append("pause")
        if "email-beat" in self.items:
            self.items["email-beat"]["State"]["Running"] = False
        self.trigger("early-drain")
        for name in self.workers:
            if name in self.items:
                self.items[name]["State"]["Running"] = False

    def start_candidates(self, config: dict) -> None:
        self.events.append("start-candidates")
        for name in WEB:
            identifier = "candidate-" + name
            self.record["candidates"][name] = identifier
            self.stages[identifier] = {"State": {"Running": True}}
        self.trigger("candidate-preflight")

    def live_capacity(self, config: dict, *, workers_paused: bool = False) -> None:
        if workers_paused:
            assert not any(self.items[name]["State"]["Running"] for name in self.workers if name in self.items)
        self.events.append("capacity-verified")

    def route(self, identifiers: dict | None) -> None:
        values = list(identifiers.values()) if identifiers else []
        route = "candidate" if values and values[0].startswith("candidate") else "original"
        self.events.append("route-" + route)

    def drain_upstreams(self, identifiers: dict) -> None:
        self.events.append("drain-upstreams")
        self.trigger("old-web-drain")

    def public_probe(self, revision: str, *, full: bool = False) -> None:
        self.events.append("public-" + ("old" if revision == PREVIOUS else "new"))
        if revision == REVISION:
            self.trigger("after-route")

    def update_originals(self, services: tuple[str, ...], *, previous: bool = False) -> None:
        label = "web" if services == WEB else "workers"
        self.events.append("update-" + label + ("-old" if previous else "-new"))
        for name in services:
            prefix = "old" if previous else "new"
            self.items.setdefault(name, {"State": {}, "Config": {"Hostname": name}})
            self.items[name].update(Id=f"{prefix}-{name}", Image=f"{prefix}-image-{name}")
            self.items[name]["State"]["Running"] = True
        if not previous:
            missing = "frontend" if label == "web" else "email-worker"
            if self.failure == "partial-" + label and not self.failed:
                del self.items[missing]
                self.trigger("partial-" + label)

    def wait_web(self, identifiers: dict, revision: str, *, full: bool = False) -> None:
        self.events.append("web-ready-" + ("old" if revision == PREVIOUS else "new"))
        if full and revision == REVISION:
            self.trigger("late-full-readiness")

    def wait_workers(self) -> None:
        self.events.append("workers-ready")

    def restore_consumers(self) -> None:
        self.events.append("consumers-restored")

    def verify_containers(self, services, images) -> None:
        pass

    def container(self, name: str) -> dict:
        item = self.items.get(name)
        if item is None or not item["State"].get("Running"):
            raise ReleaseError("Container absent or stopped: " + name)
        return item

    def existing(self, name: str) -> dict:
        return self.items[name]

    def optional_existing(self, name: str) -> dict | None:
        return self.items.get(name)

    def inspect(self, identifier: str, *, image: bool = False) -> dict:
        return self.stages[identifier]

    def stop_candidates(self) -> None:
        self.events.append("stop-candidates")
        for item in self.stages.values():
            item["State"]["Running"] = False

    def dc(self, *args, **kwargs) -> str:
        assert args == ("config", "--format", "json"), args
        return "{}"

    def run(self, *args, **kwargs) -> str:
        assert args[:2] == ("docker", "start"), args
        for identifier in args[2:]:
            self.events.append("start-" + identifier)
            if identifier in self.stages:
                self.stages[identifier]["State"]["Running"] = True
            else:
                next(item for item in self.items.values() if item["Id"] == identifier)["State"]["Running"] = True
        return ""


class SafetyContracts(unittest.TestCase):
    def payload(self) -> dict:
        return {"revision": REVISION, "checks": {"database": "ok"}, "status": "degraded",
                "capabilities": {**{name: {"required": True, "available": True} for name in CORE_CAPABILITIES},
                                 "background_processing": {"required": True, "available": False}}}

    def test_partial_readiness_allows_only_background_pause(self) -> None:
        payload = self.payload()
        validate_readiness(payload, REVISION, full=False)
        with self.assertRaises(ReleaseError):
            validate_readiness(payload, REVISION, full=True)
        payload["capabilities"]["object_storage"]["available"] = False
        with self.assertRaises(ReleaseError):
            validate_readiness(payload, REVISION, full=False)

    def test_revision_and_capabilities_cannot_be_omitted(self) -> None:
        for key in ("revision", "capabilities"):
            payload = self.payload()
            del payload[key]
            with self.assertRaises(ReleaseError):
                validate_readiness(payload, REVISION, full=False)

    def test_capacity_counts_foreign_containers_and_reserve(self) -> None:
        running = [{"Id": "infra-and-web", "HostConfig": {"Memory": 10176 * MIB}},
                   {"Id": "workers", "HostConfig": {"Memory": 3712 * MIB}}]
        report = validate_capacity(running, {"workers"}, 3072 * MIB, 15992 * MIB)
        self.assertEqual(report["web_overlap_bytes"], 13248 * MIB)
        with self.assertRaises(ReleaseError):
            validate_capacity(running, set(), 3072 * MIB, 15992 * MIB)
        running.append({"Id": "foreign", "HostConfig": {"Memory": 1024 * MIB}})
        with self.assertRaises(ReleaseError):
            validate_capacity(running, {"workers"}, 3072 * MIB, 15992 * MIB)

    def test_unbounded_foreign_container_refuses_staging(self) -> None:
        with self.assertRaises(ReleaseError):
            validate_capacity([{"Id": "foreign", "HostConfig": {"Memory": 0}}], set(), 512 * MIB, 15992 * MIB)

    def test_nginx_changes_only_reviewed_upstreams(self) -> None:
        result = web_configuration(NGINX, {"backend": "172.18.0.21", "frontend": "172.18.0.22"})
        self.assertEqual(result.replace("172.18.0.21", "backend").replace("172.18.0.22", "frontend"), NGINX)
        with self.assertRaises(ReleaseError):
            web_configuration(NGINX.replace("server backend", "server other"), {"backend": "172.18.0.21", "frontend": "172.18.0.22"})

    def test_task_body_may_change_but_persisted_contract_may_not(self) -> None:
        old = "@celery_app.task(name='job', queue='jobs')\ndef task(identifier: str):\n return 1\n"
        self.assertEqual(task_contract(old), task_contract(old.replace("return 1", "return 2")))
        self.assertNotEqual(task_contract(old), task_contract(old.replace("identifier: str", "identifier: str, force=False")))
        self.assertNotEqual(task_contract(old), task_contract(old.replace("queue='jobs'", "queue='other'")))

    def test_early_failure_never_recreates_running_workers_or_web(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenario = Scenario(Path(directory), "early-drain")
            with self.assertRaisesRegex(ReleaseError, "injected"):
                scenario.run_update()
            self.assertEqual(scenario.record["phase"], "recovered")
            self.assertFalse(any(event.startswith("update-") for event in scenario.events))
            self.assertIn("start-old-email-beat", scenario.events)
            self.assertIn("consumers-restored", scenario.events)

    def test_preflight_and_route_failures_restore_old_pair(self) -> None:
        for failure in ("candidate-preflight", "after-route", "old-web-drain"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                scenario = Scenario(Path(directory), failure)
                with self.assertRaisesRegex(ReleaseError, "injected"):
                    scenario.run_update()
                self.assertEqual(scenario.record["phase"], "recovered")
                self.assertFalse(any(event.startswith("update-web") for event in scenario.events))
                self.assertLess(scenario.events.index("route-original"), scenario.events.index("stop-candidates"))
                self.assertTrue(all(item["State"]["Running"] for item in scenario.items.values()))

    def test_late_failure_restages_before_replacing_only_serving_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            scenario = Scenario(Path(directory), "late-full-readiness")
            with self.assertRaisesRegex(ReleaseError, "injected"):
                scenario.run_update()
            recovering = scenario.events[scenario.events.index("recovering"):]
            self.assertLess(recovering.index("pause"), recovering.index("capacity-verified"))
            self.assertLess(recovering.index("capacity-verified"), recovering.index("start-candidate-backend"))
            self.assertLess(recovering.index("route-candidate"), recovering.index("update-web-old"))
            self.assertLess(recovering.index("route-original"), recovering.index("stop-candidates"))
            self.assertEqual(scenario.record["phase"], "recovered")
            self.assertTrue(all(item["Id"].startswith("old-") and item["State"]["Running"] for item in scenario.items.values()))

    def test_partial_compose_replacement_recovers_missing_web_and_worker(self) -> None:
        for failure in ("partial-web", "partial-workers"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                scenario = Scenario(Path(directory), failure)
                with self.assertRaisesRegex(ReleaseError, "injected"):
                    scenario.run_update()
                recovering = scenario.events[scenario.events.index("recovering"):]
                self.assertLess(recovering.index("route-candidate"), recovering.index("update-web-old"))
                self.assertEqual(scenario.record["phase"], "recovered")
                self.assertEqual(set(scenario.items), set(scenario.activated_services))
                self.assertTrue(all(item["Id"].startswith("old-") and item["State"]["Running"] for item in scenario.items.values()))

    def test_nginx_drain_ignores_live_original_generation_during_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = CodeUpdate(REVISION, Path(directory), Path(directory) / "signed.json")
            release.record = {"nginx_bindings": {"1": ["original"], "2": ["candidate"]}}
            release.nginx_workers = Mock(side_effect=[{"1", "2"}, {"1"}])
            with patch("release_code_update.time.sleep"):
                release.drain_upstreams({"backend": "candidate"})
            self.assertEqual(release.nginx_workers.call_count, 2)

    def test_nginx_drain_refuses_to_stop_pair_with_inflight_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = CodeUpdate(REVISION, Path(directory), Path(directory) / "signed.json")
            release.record = {"nginx_bindings": {"1": ["original"]}}
            release.nginx_workers = Mock(return_value={"1"})
            with patch("release_code_update.time.sleep"), self.assertRaisesRegex(ReleaseError, "retaining both"):
                release.drain_upstreams({"backend": "original"})

    def test_binding_rejects_environment_or_overlay_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            import hashlib
            root = Path(directory)
            release = CodeUpdate(REVISION, root, root / "signed.json")
            release.directory.mkdir(parents=True)
            overlay = root / "compose.json"
            overlay.write_text("{}")
            release.original_env.write_text("APP_REVISION=" + PREVIOUS + "\nSECRET=retained\n")
            release.original_nginx.write_text(NGINX)
            (root / ".env").write_text(release.original_env.read_text())
            release.record = {"compose_sha256": {str(overlay): hashlib.sha256(overlay.read_bytes()).hexdigest()},
                              "original_env_sha256": hashlib.sha256(release.original_env.read_bytes()).hexdigest(),
                              "original_nginx_sha256": hashlib.sha256(release.original_nginx.read_bytes()).hexdigest()}
            release.verify_binding()
            (root / ".env").write_text("SECRET=changed\n")
            with self.assertRaisesRegex(ReleaseError, "environment changed"):
                release.verify_binding()
            (root / ".env").write_text(release.original_env.read_text())
            overlay.write_text('{"changed":true}')
            with self.assertRaisesRegex(ReleaseError, "overlay changed"):
                release.verify_binding()


if __name__ == "__main__":
    unittest.main()
