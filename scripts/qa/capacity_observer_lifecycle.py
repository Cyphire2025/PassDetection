"""Drain the local observer subprocess owned by a workload qualification run."""

from __future__ import annotations

import asyncio
import sys

from run_qualification_stack import ROOT

# Standalone QA commands run from scripts/qa, outside pytest's backend path.
# The reused helper and its package initializers import only standard-library code.
sys.path.append(str(ROOT / "backend"))

from app.infrastructure.documents.storage_transfers import (  # noqa: E402
    finish_cleanup_despite_cancellation,
)

OBSERVER_STOP_TIMEOUT_SECONDS = 10


async def _stop_local_observer(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=OBSERVER_STOP_TIMEOUT_SECONDS)
    except TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await asyncio.wait_for(process.wait(), timeout=OBSERVER_STOP_TIMEOUT_SECONDS)


async def finish_observer(process: asyncio.subprocess.Process) -> None:
    """Reap this local CLI handle even when its caller is repeatedly cancelled.

    Stopping Docker's CLI is not proof that remote docker-exec work stops at the
    same instant. The fixture reader has its own separate deadlines; live remote
    completion still requires service qualification.
    """
    await finish_cleanup_despite_cancellation(_stop_local_observer(process))
