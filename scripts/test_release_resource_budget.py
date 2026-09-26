"""Exercise phase exclusion only when kernel/container evidence permits it."""
import unittest

from release_resource_budget import admit_live_phase, plan_release_phases


def service(memory, **kwargs):
    return {"mem_limit": memory, "cpus": 1, **kwargs}


def config():
    return {"services": {
        "backend": service("2g"), "worker": service("512m", command=["celery", "worker", "-c", "1"]),
        "db": service("1g"), "minio": service("512m"),
        **{name: service("512m", profiles=["maintenance"], restart="no")
           for name in ("database-admin", "database-migrate", "storage-stage", "storage-copy")}}}


def running(identity, name, memory, project="existing"):
    return {"Id": identity, "State": {"Running": True}, "HostConfig": {"Memory": memory},
            "Config": {"Labels": {"com.docker.compose.project": project, "com.docker.compose.service": name}}}


class ReleaseMemoryBudgetTests(unittest.TestCase):
    def test_planned_maintenance_excludes_only_declared_writers_and_never_runs_both_db_helpers(self):
        result = plan_release_phases(config(), host_memory_bytes=6 * 1024**3, writers={"backend", "worker"})
        self.assertFalse(result["errors"])
        self.assertEqual(result["phases"]["steady"]["container_bytes"], 4 * 1024**3)
        self.assertEqual(result["phases"]["database-admin"]["services"], ["database-admin", "db", "minio"])
        self.assertEqual(result["phases"]["storage-copy"]["container_bytes"], int(2.5 * 1024**3))

    def test_candidate_overcommit_and_unknown_profiles_are_rejected(self):
        self.assertTrue(plan_release_phases(config(), host_memory_bytes=5 * 1024**3, writers={"backend", "worker"})["errors"])
        for mutation in ({"profiles": []}, {"restart": "always"}):
            changed = config()
            changed["services"]["database-admin"].update(mutation)
            with self.assertRaises(ValueError):
                plan_release_phases(changed, host_memory_bytes=8 * 1024**3, writers={"backend", "worker"})

    def test_live_gate_includes_unrelated_containers_and_refuses_unbounded_caps(self):
        for memory in (4 * 1024**3, 0):
            with self.assertRaises(ValueError):
                admit_live_phase(config(), host_memory_bytes=6 * 1024**3, project="existing",
                    running_containers=[running("other", "unrelated", memory, project="different")],
                    starting_services={"database-admin"}, required_stopped={"backend", "worker"})

    def test_a_profile_label_does_not_prove_a_writer_or_helper_is_stopped(self):
        for name in ("backend", "worker", "database-admin", "database-migrate", "storage-copy"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                admit_live_phase(config(), host_memory_bytes=8 * 1024**3, project="existing",
                    running_containers=[running("live", name, 128 * 1024**2)],
                    starting_services={"database-migrate"}, required_stopped={"backend", "worker"})

    def test_one_inspected_staging_provider_can_overlap_exactly_one_copy_helper(self):
        result = admit_live_phase(config(), host_memory_bytes=6 * 1024**3, project="existing",
            running_containers=[running("db", "db", 1024**3), running("stage", "storage-stage", 512 * 1024**2)],
            starting_services={"storage-copy"}, required_stopped={"backend", "worker"})
        self.assertEqual(result["live_container_bytes"], int(1.5 * 1024**3))
        self.assertEqual(result["starting_container_bytes"], 512 * 1024**2)

    def test_db_helpers_cannot_be_approved_concurrently(self):
        with self.assertRaises(ValueError):
            admit_live_phase(config(), host_memory_bytes=64 * 1024**3, project="existing",
                running_containers=[], starting_services={"database-admin", "database-migrate"}, required_stopped={"backend"})

    def test_persistent_replacement_counts_remaining_and_foreign_caps(self):
        changed = config()
        changed["services"]["clamav"] = service("3g")
        for name in ("db", "clamav"):
            with self.subTest(name=name):
                existing = [running("redis", "redis", 512 * 1024**2),
                            running("foreign", "other", 1024**3, project="another")]
                result = admit_live_phase(changed, host_memory_bytes=8 * 1024**3,
                    project="existing", running_containers=existing,
                    starting_services={name}, required_stopped={"backend", "worker"})
                self.assertEqual(result["live_container_bytes"], int(1.5 * 1024**3))
                self.assertEqual(result["starting_container_bytes"],
                                 (1 if name == "db" else 3) * 1024**3)
                with self.assertRaisesRegex(ValueError, "exceed physical memory"):
                    admit_live_phase(changed, host_memory_bytes=(3 if name == "db" else 5) * 1024**3,
                        project="existing", running_containers=existing,
                        starting_services={name}, required_stopped={"backend", "worker"})

    def test_persistent_replacement_requires_stopped_original_and_all_writers(self):
        changed = config()
        changed["services"]["clamav"] = service("3g")
        for replacement in ("db", "clamav"):
            for live in (replacement, "backend", "worker", "storage-stage", "storage-copy", "database-admin"):
                with self.subTest(replacement=replacement, live=live), self.assertRaises(ValueError):
                    admit_live_phase(changed, host_memory_bytes=16 * 1024**3,
                        project="existing", running_containers=[running("live", live, 1024**3)],
                        starting_services={replacement}, required_stopped={"backend", "worker"})

    def test_persistent_admission_cannot_restart_redis_or_batch_other_services(self):
        changed = config()
        changed["services"].update(clamav=service("3g"), redis=service("512m"))
        for names in ({"redis"}, {"db", "clamav"}, {"db", "database-admin"}, {"clamav", "backend"}):
            with self.subTest(names=names), self.assertRaises(ValueError):
                admit_live_phase(changed, host_memory_bytes=64 * 1024**3,
                    project="existing", running_containers=[], starting_services=names,
                    required_stopped={"backend", "worker"})

    def test_persistent_replacement_refuses_unknown_or_unbounded_live_inventory(self):
        for item in (running("foreign", "other", 0, project="another"),
                     running("", "other", 1024**3, project="another")):
            with self.subTest(item=item), self.assertRaises(ValueError):
                admit_live_phase(config(), host_memory_bytes=64 * 1024**3,
                    project="existing", running_containers=[item], starting_services={"db"},
                    required_stopped={"backend", "worker"})


if __name__ == "__main__":
    unittest.main()
