"""Run network-isolated maximum accepted synthetic parser inputs; retain evidence.

Measures actual cgroup peaks, including the fully imported Celery parent and
forked child. This bounded experiment is not a complete VPS profile approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, cwd=ROOT, stderr=subprocess.STDOUT)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--memory", default="2g")
    parser.add_argument("--children", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--repetitions", type=int, choices=range(1, 21), default=1)
    parser.add_argument("--source-checkout", action="store_true", help="Use the current application source in this network-isolated probe only")
    parser.add_argument("--modes", nargs="+", default=["baseline", "passport-rgb", "passport-rgba", "gemini-extraction", "gemini-verification", "extraction", "extraction-full", "ecr", "email", "visa-image", "crop"])
    args = parser.parse_args()
    if not args.image.startswith("sha256:") or len(args.image) != 71:
        parser.error("Supply a verified immutable local image ID")
    if any(mode not in {"baseline", "passport-rgb", "passport-rgba", "extraction", "extraction-full", "ecr", "ecr-single", "email", "visa-image", "crop", "gemini-extraction", "gemini-verification"} for mode in args.modes):
        parser.error("Only fixed synthetic workload modes are permitted")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    output = ROOT / "outputs" / "memory-qualification" / run_id
    output.mkdir(parents=True)
    fixtures = output / "fixtures"
    fixtures.mkdir()
    common = ["docker", "run", "--network", "none", "--user", "1001:1001", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges:true", "--pids-limit", "128", "--memory", args.memory,
              "--memory-swap", args.memory, "--cpus", "2", "--entrypoint", "python",
              "--mount", f"type=bind,src={ROOT / 'scripts' / 'qa'},dst=/qa,readonly",
              "-e", "APP_ENV=development", "-e", "APP_SECRET_KEY=synthetic-memory-probe-secret-only-2026",
              "-e", "POSTGRES_DB=passdetection_ci_memory", "-e", "POSTGRES_USER=synthetic_memory",
              "-e", "POSTGRES_PASSWORD=synthetic-memory-only", "-e", "PROCESSING_BACKEND=celery",
              "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "OMP_THREAD_LIMIT=1", "-e", "OPENBLAS_NUM_THREADS=1"]
    source_hashes = {}
    if args.source_checkout:
        common.extend(["--mount", f"type=bind,src={ROOT / 'backend' / 'app'},dst=/app/app,readonly"])
        source_hashes = {str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted((ROOT / "backend/app").rglob("*.py"))}
    generator = [*common, "--name", f"pd-memory-{run_id}-fixtures", "--mount", f"type=bind,src={fixtures},dst=/fixtures",
                 args.image, "/qa/probe_bounded_memory.py", "generate"]
    (output / "generator.log").write_text(command(*generator), encoding="utf-8")
    receipts = []
    for mode in args.modes:
        name = f"pd-memory-{run_id}-{mode}"
        invocation = [*common, "--name", name, "--mount", f"type=bind,src={fixtures},dst=/fixtures,readonly",
                      args.image, "/qa/probe_bounded_memory.py", mode, "--children", str(args.children),
                      "--repetitions", str(args.repetitions)]
        result = subprocess.run(invocation, text=True, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, check=False)
        (output / f"{mode}.log").write_text(result.stdout, encoding="utf-8")
        state = json.loads(command("docker", "inspect", name))[0]
        parsed = None
        for line in reversed(result.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except ValueError:
                continue
            if isinstance(candidate, dict) and candidate.get("mode") == mode:
                parsed = candidate
                break
        receipt = {"mode": mode, "container": name, "returncode": result.returncode,
                   "oom_killed": state["State"]["OOMKilled"], "measurements": parsed}
        receipts.append(receipt)
        print(json.dumps(receipt), flush=True)
        (output / "evidence.json").write_text(json.dumps({"image": args.image, "memory_limit": args.memory,
            "children": args.children, "repetitions": args.repetitions, "source_checkout": args.source_checkout, "application_source_hashes": source_hashes,
            "source_sha256": hashlib.sha256((ROOT / "scripts/qa/probe_bounded_memory.py").read_bytes()).hexdigest(),
            "fixtures": json.loads((fixtures / "manifest.json").read_text()), "workloads": receipts,
            "limitations": ["No external providers, production data or malware scanner exercised", "Not a full-stack or steady-state capacity claim", "Exited synthetic containers retained"]}, indent=2), encoding="utf-8")
    if any(item["returncode"] != 0 or item["oom_killed"] for item in receipts):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
