"""Historical companion to recover_worker_deployment.py for the 0092 deployment.

Run through docker exec stdin; identify and warm-stop only Celery's main process.
Review the recovery helper's deployment assumptions before reuse.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

APP = "app.infrastructure.processing.celery_app:celery_app"


def arguments(pid: int, proc: Path) -> list[str]:
    return (proc / str(pid) / "cmdline").read_bytes().decode().rstrip("\0").split("\0")


def is_celery(args: list[str], role: str) -> bool:
    # Only the executable/script prefix may identify Celery, never a shell string.
    if not any(Path(arg).name == "celery" for arg in args[:2]):
        return False
    try:
        index = args.index("-A")
        return args[index + 1 : index + 3] == [APP, role]
    except ValueError:
        return False


def identify(role: str, proc: Path = Path("/proc")) -> dict[str, object]:
    if role not in {"worker", "beat"}:
        raise RuntimeError("Unsupported process role")
    if os.environ.get("REMAP_SIGTERM", "").upper() in {"QUIT", "SIGQUIT"}:
        raise RuntimeError("Cold-shutdown SIGTERM remapping is not safe for this helper")
    first = arguments(1, proc)
    if is_celery(first, role):
        pid = 1
    else:
        if Path(first[0]).name not in {"sh", "dash", "bash"}:
            raise RuntimeError("Unexpected PID 1; refusing to signal any process")
        children = (proc / "1/task/1/children").read_text().split()
        candidates = []
        for child in children:
            try:
                if is_celery(arguments(int(child), proc), role):
                    candidates.append(int(child))
            except FileNotFoundError:
                continue
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one direct Celery child of PID 1")
        pid = candidates[0]
    # Linux stat field 22, after the parenthesized command name and field 3.
    started = (proc / str(pid) / "stat").read_text().rsplit(") ", 1)[1].split()[19]
    return {"pid": pid, "started": started, "role": role}


def main() -> None:
    mode, role = sys.argv[1:3]
    current = identify(role)
    if mode == "stop":
        expected = json.loads(sys.argv[3])
        if current != expected:
            raise RuntimeError("Celery process changed since preflight; refusing stale signal")
        os.kill(int(current["pid"]), signal.SIGTERM)
    elif mode != "check":
        raise RuntimeError("Unsupported probe mode")
    print(json.dumps(current), flush=True)


if __name__ == "__main__":
    main()
