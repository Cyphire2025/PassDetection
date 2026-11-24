"""Run the final image's native crops over real four-worker Gunicorn HTTP."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qa.owned_probe_container import OwnedProbeContainer, error_types

ROOT = Path(__file__).resolve().parents[2]


def command(*args: str, timeout: int = 120):
    return subprocess.check_output(
        args, cwd=ROOT, text=True, stderr=subprocess.STDOUT, timeout=timeout
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--source-admission",
        action="store_true",
        help="Diagnostic read-only admission module overlay; not final-image proof",
    )
    args = parser.parse_args()
    assert args.image.startswith("sha256:") and len(args.image) == 71
    assert (
        command("docker", "image", "inspect", args.image, "--format", "{{.Id}}").strip()
        == args.image
    )
    name = "pd-api-memory-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output = ROOT / "outputs/memory-qualification" / name
    output.mkdir(parents=True)
    fixtures = output / "fixtures"
    fixtures.mkdir()
    source = ROOT / "scripts/qa/api_native_memory_app.py"
    common = [
        "docker",
        "run",
        "--network",
        "none",
        "--user",
        "1001:1001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "256",
        "--no-healthcheck",
        "--memory",
        "2560m",
        "--memory-swap",
        "2560m",
        "--cpus",
        "4",
        "-e",
        "APP_ENV=development",
        "-e",
        "APP_SECRET_KEY=synthetic-memory-probe-secret-only-2026",
        "-e",
        "POSTGRES_DB=passdetection_ci_memory",
        "-e",
        "POSTGRES_PASSWORD=synthetic-only",
        "-e",
        "WEB_CONCURRENCY=4",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "--mount",
        f"type=bind,src={source},dst=/qa/api_native_memory_app.py,readonly",
    ]
    if args.source_admission:
        common.extend(
            [
                "--mount",
                f"type=bind,src={ROOT / 'backend/app/core/native_image_admission.py'},dst=/app/app/core/native_image_admission.py,readonly",
            ]
        )
    generate = """import hashlib,io; from PIL import Image; from pathlib import Path
with Image.new('RGB',(6000,4000),(220,230,240)) as image:
 buffer=io.BytesIO(); image.save(buffer,format='PNG'); content=buffer.getvalue()
content += b'\\0' * (10*1024*1024-len(content))
Path('/fixtures/input.png').write_bytes(content)
Path('/fixtures/input.sha256').write_text(hashlib.sha256(content).hexdigest())
"""
    command(
        *common,
        "--rm",
        "--mount",
        f"type=bind,src={fixtures},dst=/fixtures",
        args.image,
        "python",
        "-c",
        generate,
    )
    owned = OwnedProbeContainer(name, args.image)
    host_admission_sha256 = hashlib.sha256(
        (ROOT / "backend/app/core/native_image_admission.py").read_bytes()
    ).hexdigest()
    receipt = {
        "image": args.image,
        "name": name,
        "status": "failed",
        "source_admission_overlay": args.source_admission,
        "host_admission_sha256": host_admission_sha256,
        "memory_limit_bytes": 2560 * 1024**2,
        "workers": 4,
        "cpus": 4,
        "fixture_sha256": (fixtures / "input.sha256").read_text().strip(),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "limits": [
            "QA-only endpoint, not production authorization/storage/DB qualification",
            "Complete real app imported; lifespan and external dependencies disabled",
            "Network none; client memory is conservatively included in measured cgroup",
            "Encoded input padded to10MiB; real24MP45degree strongest-sharpness transform",
            "No production data, volume or service changed; stopped probe retained",
        ],
    }
    errors: list[BaseException] = []
    try:
        container = command(
            *common,
            "--detach",
            *owned.options(),
            "--mount",
            f"type=bind,src={fixtures},dst=/fixtures,readonly",
            args.image,
            "gunicorn",
            "--chdir",
            "/qa",
            "--pythonpath",
            "/app",
            "--workers",
            "4",
            "--bind",
            "0.0.0.0:8000",
            "--worker-class",
            "app.infrastructure.bounded_uvicorn_worker.BoundedUvicornWorker",
            "--timeout",
            "120",
            "--graceful-timeout",
            "30",
            "api_native_memory_app:app",
        ).strip()
        owned.bind_returned_id(container)
        receipt["container"] = container
        admission_probe = "import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/app/app/core/native_image_admission.py').read_bytes()).hexdigest())"
        measured_admission = command(
            "docker", "exec", container, "python", "-c", admission_probe, timeout=10
        ).strip()
        if len(measured_admission) != 64 or any(
            value not in "0123456789abcdef" for value in measured_admission
        ):
            raise ValueError("Measured container admission source hash is invalid")
        if args.source_admission and measured_admission != host_admission_sha256:
            raise ValueError(
                "The measured source-admission overlay differs from this checkout"
            )
        receipt["admission_sha256"] = measured_admission
        ready = "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/ready',timeout=2).read().decode())"
        for attempt in range(60):
            try:
                command("docker", "exec", container, "python", "-c", ready, timeout=5)
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        else:
            raise RuntimeError("Isolated API never became ready")
        before = command("docker", "top", container, "-eo", "pid,ppid,args")
        try:
            result = command(
                "docker",
                "exec",
                "-e",
                "PYTHONPATH=/app",
                container,
                "python",
                "/qa/api_native_memory_app.py",
                timeout=180,
            )
        except subprocess.CalledProcessError as error:
            try:
                (output / "probe.log").write_text(error.output, encoding="utf-8")
            except BaseException as diagnostic_error:  # noqa: BLE001 - preserve the original probe error.
                errors.extend([error, diagnostic_error])
            raise
        (output / "probe.log").write_text(result, encoding="utf-8")
        payload = json.loads(result.splitlines()[-1])
        after = command("docker", "top", container, "-eo", "pid,ppid,args")
        assert before == after, "API worker process changed during memory pressure"
        receipt.update(status="passed", results=payload, worker_processes=before)
    except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
        if not errors:
            errors.append(error)
    finally:
        state = None
        try:
            state = owned.inspect_owned(command)["State"]
            receipt["state_before_stop"] = state
        except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
            errors.append(error)
        memory_probe = "import json;from pathlib import Path;p=Path('/sys/fs/cgroup');print(json.dumps({n:(p/n).read_text() for n in ('memory.current','memory.peak','memory.max','memory.events')}))"
        if state is not None and state.get("Running") and owned.identifier is not None:
            try:
                receipt["terminal_cgroup"] = json.loads(
                    command(
                        "docker",
                        "exec",
                        owned.identifier,
                        "python",
                        "-c",
                        memory_probe,
                        timeout=10,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
                errors.append(error)
        if owned.identifier is not None:
            try:
                (output / "server.log").write_text(
                    command("docker", "logs", owned.identifier, timeout=10),
                    encoding="utf-8",
                )
            except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
                errors.append(error)
        cleanup = owned.finish(command)
        errors.extend(cleanup.errors)
        receipt["container"] = owned.identifier
        if cleanup.after is not None:
            receipt["state_after_stop"] = cleanup.after
        if errors:
            receipt.update(status="failed", error_types=error_types(errors))
        try:
            (output / "evidence.json").write_text(
                json.dumps(receipt, indent=2), encoding="utf-8"
            )
        except BaseException as error:  # noqa: BLE001 - defer errors until owned cleanup finishes.
            errors.append(error)
    if errors:
        raise errors[0]
    print(
        json.dumps(
            {"receipt": str(output / "evidence.json"), "status": receipt["status"]}
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
