"""Same-schema app release over inspected containers, retaining every prior resource.

Full mode consumes verified CI images. Fast mode builds source on the VPS and
explicitly has lower assurance. Neither path runs migrations or deletes data,
containers, images, volumes, builders or release evidence. A bounded ingress
pause is expected; this is not a zero-downtime deployment.
"""

from __future__ import annotations

import argparse as argparse
import hashlib as hashlib
import json as json
import os as os
import re as re
import shutil as shutil
import signal as signal
import subprocess as subprocess
import sys as sys
import time as time
import uuid as uuid
from collections.abc import Callable as Callable
from collections.abc import Iterator as Iterator
from contextlib import contextmanager as contextmanager
from pathlib import Path as Path
from pathlib import PurePosixPath as PurePosixPath
from types import FrameType

sys.dont_write_bytecode = True

# Preserve legacy bytecode suppression before importing release owners.

from mcp_direct_activate import clean_stop as clean_stop  # noqa: E402
from mcp_direct_build import GIB as GIB  # noqa: E402
from mcp_direct_build import BuildError as BuildError  # noqa: E402
from mcp_direct_build import RetainedBuild as RetainedBuild  # noqa: E402
from mcp_direct_build import command as command  # noqa: E402
from mcp_direct_build import contract_digest as contract_digest  # noqa: E402
from mcp_direct_containers import LocalDocker as LocalDocker  # noqa: E402
from mcp_direct_containers import clone_payload as clone_payload  # noqa: E402
from mcp_direct_release import bound_original as bound_original  # noqa: E402
from mcp_direct_release import wait_for_idle as wait_for_idle  # noqa: E402
from mcp_direct_state import APPLICATION as APPLICATION  # noqa: E402
from mcp_direct_state import INFRASTRUCTURE as INFRASTRUCTURE  # noqa: E402
from mcp_direct_state import WORKERS as WORKERS  # noqa: E402
from mcp_direct_state import private_json as private_json  # noqa: E402
from release_artifacts import verify_manifest as verify_manifest  # noqa: E402
from release_code_update import COMPATIBILITY_PATHS as COMPATIBILITY_PATHS  # noqa: E402
from release_code_update import environment as environment  # noqa: E402
from release_code_update import task_contract as task_contract  # noqa: E402
from release_code_update import validate_readiness as validate_readiness  # noqa: E402
from release_manifest import load_release_manifest as load_release_manifest  # noqa: E402
from release_traveller_whatsapp import ReleaseError as ReleaseError  # noqa: E402
from release_traveller_whatsapp import release_lock as release_lock  # noqa: E402
from retained_release_contract import ACTIVE as ACTIVE  # noqa: E402
from retained_release_contract import (  # noqa: E402
    ADDITIONAL_CONTRACT_PATHS as ADDITIONAL_CONTRACT_PATHS,
)
from retained_release_contract import FULL_BUILD_PATHS as FULL_BUILD_PATHS  # noqa: E402
from retained_release_contract import ORIGIN as ORIGIN  # noqa: E402
from retained_release_contract import REVISION as REVISION  # noqa: E402
from retained_release_contract import ROOT as ROOT  # noqa: E402
from retained_release_contract import ROUTE_ALLOWLIST as ROUTE_ALLOWLIST  # noqa: E402
from retained_release_contract import SCHEMA as SCHEMA  # noqa: E402
from retained_release_contract import SERVICES as SERVICES  # noqa: E402
from retained_release_contract import forbidden_changes as forbidden_changes  # noqa: E402
from retained_release_contract import proxy_configuration as proxy_configuration  # noqa: E402
from retained_release_contract import require as require  # noqa: E402
from retained_release_contract import runtime_environment as runtime_environment  # noqa: E402
from retained_release_contract import select_live as select_live  # noqa: E402
from retained_release_contract import (  # noqa: E402
    validate_route_allowlist as validate_route_allowlist,
)
from retained_release_contract import wait_full_readiness as wait_full_readiness  # noqa: E402
from retained_release_fast import FastBuild as FastBuild  # noqa: E402
from retained_release_lifecycle import RetainedUpdate as RetainedUpdate  # noqa: E402


def release_for_source(
    source: Path, revision: str, mode: str, artifact: Path | None
) -> RetainedUpdate:
    manifest = load_release_manifest(source / "backend/app/core/config/release_manifest.json")
    if manifest.get("deployment_kind") == "workspace_branding_v1":
        from release_workspace_branding import WorkspaceBrandingUpdate

        return WorkspaceBrandingUpdate(source, revision, mode, artifact)
    if manifest.get("deployment_kind") == "document_distribution_updates_v1":
        from release_document_retained_update import DocumentRetainedUpdate

        return DocumentRetainedUpdate(source, revision, mode, artifact)
    if manifest.get("deployment_kind") == "companies_traveller_reuse_v1":
        from release_companies_retained_update import CompaniesRetainedUpdate

        return CompaniesRetainedUpdate(source, revision, mode, artifact)
    return RetainedUpdate(source, revision, mode, artifact)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--mode", choices=("full", "fast"), required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--recover-receipt", type=Path)
    parser.add_argument(
        "--pause-email-and-photos",
        action="store_true",
        help="Pause three feature workers and allocate 3584 MiB to the backend; retain the shared scheduler",
    )
    args = parser.parse_args()
    os.umask(0o077)
    release = release_for_source(
        Path(__file__).resolve().parents[1], args.revision, args.mode, args.manifest
    )
    release.pause_email_and_photos = args.pause_email_and_photos

    def interrupted(signum: int, frame: FrameType | None) -> None:
        raise ValueError("release_interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    with release_lock(ROOT / "tmp/compose-release-lock"):
        if args.recover_receipt:
            require(
                args.recover_receipt.resolve().parent == release.directory
                and not args.recover_receipt.is_symlink(),
                "recovery_receipt_outside_attempt",
            )
            release.record = json.loads(args.recover_receipt.read_text())
            require(
                release.record.get("source") == str(release.source)
                and release.record.get("revision") == release.revision
                and release.record.get("mode") == release.mode
                and release.record.get("pause_email_and_photos", False)
                == args.pause_email_and_photos,
                "recovery_receipt_binding_changed",
            )
            release.recover()
        else:
            release.run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Docker/configuration/provider errors can contain credentials. Full
        # operator receipts are private; publish only a bounded local reason.
        reason = (
            str(error)
            if isinstance(error, ValueError) and re.fullmatch("[a-z_]{1,100}", str(error))
            else "release_check_failed"
        )
        print(
            json.dumps(
                {
                    "status": "stopped",
                    "reason": reason,
                    "error_type": type(error).__name__,
                    "automatic_retry": False,
                    "cleanup_performed": False,
                }
            ),
            flush=True,
        )
        raise SystemExit(1) from None
