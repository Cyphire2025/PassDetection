"""Two-stage VPS release for the traveller WhatsApp feature (migration 0093).

Run prepare while the current site is available. Pause new uploads and message
sends before activate; its worker snapshots are a gate, not a traffic barrier.
This helper never pulls/reset/stashes Git, purges queues, or restarts infrastructure.
"""

from __future__ import annotations

import argparse as argparse
import contextlib as contextlib
import copy as copy
import hashlib as hashlib
import json as json
import os as os
import re as re
import subprocess as subprocess
import sys as sys
import tempfile as tempfile
import time as time
from collections.abc import Iterator
from pathlib import Path as Path
from typing import Any as Any

from traveller_release_contract import ACTIVATED as ACTIVATED
from traveller_release_contract import CONTROL_PROBE as CONTROL_PROBE
from traveller_release_contract import NODE_PREFIXES as NODE_PREFIXES
from traveller_release_contract import PREVIOUS_SCHEMA as PREVIOUS_SCHEMA
from traveller_release_contract import PROBE_MARKER as PROBE_MARKER
from traveller_release_contract import PROJECT_LABEL as PROJECT_LABEL
from traveller_release_contract import PUBLIC_URL as PUBLIC_URL
from traveller_release_contract import READY_PROBE as READY_PROBE
from traveller_release_contract import ROOT as ROOT
from traveller_release_contract import SCHEMA as SCHEMA
from traveller_release_contract import SERVICE_LABEL as SERVICE_LABEL
from traveller_release_contract import WORKERS as WORKERS
from traveller_release_contract import ReleaseError as ReleaseError
from traveller_release_contract import image_reference as image_reference
from traveller_release_contract import updated_environment as updated_environment
from traveller_release_contract import validate_worker_probe as validate_worker_probe
from traveller_release_lifecycle import Release as Release


@contextlib.contextmanager
def release_lock(directory: Path) -> Iterator[None]:
    # Linux VPS advisory lock is released by the kernel even if the helper is interrupted.
    import fcntl

    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        directory.chmod(0o700)
    with (directory / "release.lock").open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ReleaseError("Another Compose release helper is running") from error
        yield


def main(release_type: type[Release] = Release, *, description: str | None = None) -> int:
    parser = argparse.ArgumentParser(description=description or __doc__)
    parser.add_argument("mode", choices=("prepare", "activate"))
    parser.add_argument("--revision", required=True, help="Full pushed main commit SHA")
    parser.add_argument(
        "--traffic-paused",
        action="store_true",
        help="Confirm new uploads/message sends are paused for activation",
    )
    args = parser.parse_args()
    try:
        release = release_type(args.revision)
        if args.mode == "activate" and not args.traffic_paused:
            raise ReleaseError(
                "Pause new uploads and message sends, then use activate --traffic-paused"
            )
        with release_lock(release.lock_directory):
            getattr(release, args.mode)()
    except (ReleaseError, ValueError, OSError) as error:
        print(
            f"STOPPED: {error}. No automatic rollback, Git changes, or queue purge was attempted.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
