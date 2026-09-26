"""Verify Compose naming/replica mechanics with synthetic processes and data only."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from verify_compose_runtime import BASE_COMPOSE, PROD_COMPOSE, _render_compose

IMAGE = "python:3.11.16-slim@sha256:e41613d42d4891e4930f79523f93f81bbc7632584ec65e36ab055f41a800b41e"


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def main() -> None:
    resolved = _render_compose(BASE_COMPOSE, PROD_COMPOSE)
    assert not any(service.get("container_name") for service in resolved["services"].values())
    volume_names = {key: value["name"] for key, value in resolved["volumes"].items()}
    for key, name in volume_names.items():
        assert name == f"{resolved['name']}_{key}", "Base persistent volume identity changed"
    projects = ["passdetection-topology-" + uuid.uuid4().hex[:10] for _ in range(2)]
    inventories = []
    started = []
    with tempfile.TemporaryDirectory(prefix="passdetection-topology-") as directory:
        path = Path(directory) / "compose.json"
        fixture = {"services": {}, "volumes": {"postgres_data": {}}, "networks": {"passdetection-net": {}}}
        # Preserve source service/network/volume names, replace the application
        # workload with tiny synthetic processes. This qualifies naming, not HA.
        for name in ("backend", "worker", "db"):
            source = resolved["services"][name]
            assert "passdetection-net" in source["networks"]
            fixture["services"][name] = {"image": IMAGE, "networks": ["passdetection-net"],
                "command": ["python", "-c", "import time;time.sleep(300)"]}
        fixture["services"]["db"]["volumes"] = ["postgres_data:/synthetic"]
        path.write_text(json.dumps(fixture))
        try:
            for project in projects:
                command = ["docker", "compose", "-p", project, "-f", str(path)]
                run(*command, "up", "-d", "--scale", "backend=2", "--scale", "worker=2")
                started.append(command)
                ids = run(*command, "ps", "--quiet").splitlines()
                details = json.loads(run("docker", "inspect", *ids))
                assert len(details) == 5 and all(item["State"]["Running"] for item in details)
                nodes = [item["Config"]["Hostname"] for item in details if item["Config"]["Labels"]["com.docker.compose.service"] == "worker"]
                assert len(set(nodes)) == 2
                database = next(item for item in details if item["Config"]["Labels"]["com.docker.compose.service"] == "db")
                volume = next(item["Name"] for item in database["Mounts"] if item["Destination"] == "/synthetic")
                assert volume == f"{project}_postgres_data"
                run(*command, "exec", "-T", "db", "python", "-c", "from pathlib import Path;Path('/synthetic/marker').write_text('retained synthetic data')")
                run(*command, "up", "-d", "--force-recreate", "db")
                retained = run(*command, "exec", "-T", "db", "python", "-c", "from pathlib import Path;print(Path('/synthetic/marker').read_text())")
                assert retained == "retained synthetic data"
                inventories.append({"project": project, "running_containers": len(ids), "worker_hostnames": nodes,
                                    "persistent_volume": volume, "recreate_preserved_marker": True})
            assert inventories[0]["persistent_volume"] != inventories[1]["persistent_volume"]
            receipt = {"result": "passed", "source_volume_names": volume_names, "projects": inventories,
                       "limitation": "Local Compose naming, replica host identity and volume preservation using synthetic Python processes. Application load, replica release draining and multi-host availability are not established."}
            (ROOT / "docs/remediation/compose-isolation-evidence.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt, indent=2))
        finally:
            # Stop only the synthetic projects. Retain their marker volumes;
            # never run down -v, volume rm or a global cleanup command.
            for command in started:
                run(*command, "stop")


if __name__ == "__main__":
    main()
