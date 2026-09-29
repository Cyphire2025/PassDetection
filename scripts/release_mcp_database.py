"""Exact additive database backup/migration plan for a retention-preserving executor.

The injected executor owns live container/network binding and writer fencing.
This module never launches, stops, removes or replaces a container. Every file it
creates is exclusive and retained, including failed or partial backup attempts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, Protocol

from release_mcp_contract import CHAIN, SOURCE, source_contract, validate_contract
from release_reliability import file_sha256
from release_traveller_whatsapp import ReleaseError

PGOPTIONS = "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000"
DUMP_COMMAND = (
    'set -eu; export PGPASSWORD="$POSTGRES_PASSWORD"; '
    'export PGOPTIONS="-c lock_timeout=5000 -c statement_timeout=120000"; '
    'exec pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" '
    # No --file: pg_dump treats an explicit /dev/stdout as a named file and
    # attempts fsync on Docker's pipe. The host owns the exclusive file/fsync.
    "--format=custom --lock-wait-timeout=5000"
)


class DatabaseCommand(Protocol):
    def __call__(
        self,
        arguments: tuple[str, ...],
        *,
        timeout: int,
        stdin_file: BinaryIO | None = None,
        stdout_file: BinaryIO | None = None,
    ) -> str:
        """Run inside the already-bound DB container; stream files, reject nonzero exit."""
        ...


@dataclass(frozen=True)
class ReleaseBindings:
    revision: str
    image_id: str
    database_binding_sha256: str
    writer_fence_sha256: str

    def validate(self) -> None:
        if not re.fullmatch(r"[a-f0-9]{40}", self.revision) or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", self.image_id
        ):
            raise ReleaseError("Invalid candidate revision/image binding")
        if any(
            not re.fullmatch(r"[a-f0-9]{64}", value)
            for value in (self.database_binding_sha256, self.writer_fence_sha256)
        ):
            raise ReleaseError("Exact database and writer-fence bindings are required")


def digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class MCPDatabaseRelease:
    def __init__(
        self,
        root: Path,
        directory: Path,
        bindings: ReleaseBindings,
        *,
        database_command: DatabaseCommand,
        verify_fence: Callable[[], None],
        read_schema: Callable[[], str],
    ):
        bindings.validate()
        if (
            not directory.is_absolute()
            or not directory.is_dir()
            or directory.is_symlink()
            or directory.resolve() != directory
        ):
            raise ReleaseError("An existing private release directory is required")
        if os.name == "posix" and directory.stat().st_mode & 0o077:
            raise ReleaseError("Release directory must deny group and other access")
        self.root, self.directory, self.bindings = root, directory, bindings
        self.database_command, self.verify_fence, self.read_schema = (
            database_command,
            verify_fence,
            read_schema,
        )
        self.contract = source_contract(root)
        if self.contract is None:
            raise ReleaseError("The exact additive source contract is required")
        validate_contract(self.contract, CHAIN[-1])
        self.contract_sha256 = digest_json(self.contract)

    def checkpoint(self, allowed_schemas: set[str]) -> str:
        # Callback must freshly verify ALL writer/scheduler identities, clean
        # drain, frozen state and the database/network/fence digest bindings.
        self.verify_fence()
        if source_contract(self.root) != self.contract:
            raise ReleaseError("Candidate migration source changed")
        current = self.read_schema()
        if current not in allowed_schemas:
            raise ReleaseError(
                "Database schema is outside this exact release checkpoint"
            )
        return current

    def command(
        self,
        arguments: tuple[str, ...],
        *,
        timeout: int,
        stdin_file: BinaryIO | None = None,
        stdout_file: BinaryIO | None = None,
    ) -> str:
        try:
            result = self.database_command(
                arguments,
                timeout=timeout,
                stdin_file=stdin_file,
                stdout_file=stdout_file,
            )
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            raise ReleaseError(
                "Database maintenance command failed; all artifacts retained"
            ) from None
        if not isinstance(result, str) or len(result.encode()) > 1024 * 1024:
            raise ReleaseError(
                "Database maintenance response exceeded its metadata budget"
            )
        return result

    def backup(self) -> dict[str, Any]:
        self.checkpoint({SOURCE})
        name = f"{self.bindings.revision}.{uuid.uuid4().hex}.pgdump"
        path = self.directory / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            self.command(("sh", "-c", DUMP_COMMAND), timeout=1800, stdout_file=output)
            output.flush()
            os.fsync(output.fileno())
        self.checkpoint({SOURCE})
        digest = file_sha256(path)
        with path.open("rb") as source:
            toc = self.command(("pg_restore", "--list"), timeout=180, stdin_file=source)
        if "alembic_version" not in toc or "TABLE DATA" not in toc:
            raise ReleaseError("Backup archive lacks application schema/data")
        with path.open("rb") as source:
            self.command(
                ("pg_restore", "--file=/dev/null"), timeout=1800, stdin_file=source
            )
        if file_sha256(path) != digest:
            raise ReleaseError("Backup changed during archive validation")
        record = {
            "version": 1,
            "filename": name,
            "schema": SOURCE,
            "bytes": path.stat().st_size,
            "sha256": digest,
            "created_at": datetime.now(UTC).isoformat(),
            "validation": "pg_restore_full_archive_decode",
            "restore_rehearsed": False,
            "bindings": asdict(self.bindings),
            "contract_sha256": self.contract_sha256,
        }
        self.verify_backup(record)
        self.checkpoint({SOURCE})
        self.write_receipt(name + ".json", record)
        return record

    def verify_backup(self, record: dict[str, Any]) -> Path:
        name = record.get("filename")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-f0-9]{40}\.[a-f0-9]{32}\.pgdump", name)
            or not name.startswith(self.bindings.revision + ".")
            or record.get("schema") != SOURCE
            or type(record.get("version")) is not int
            or record["version"] != 1
            or record.get("bindings") != asdict(self.bindings)
            or record.get("contract_sha256") != self.contract_sha256
            or record.get("validation") != "pg_restore_full_archive_decode"
            or record.get("restore_rehearsed") is not False
        ):
            raise ReleaseError("Backup evidence does not match this exact release")
        path = self.directory / name
        if path.is_symlink() or not path.is_file():
            raise ReleaseError("Backup is not a retained regular file")
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size != record.get("bytes")
            or info.st_size < 5
            or (os.name == "posix" and info.st_mode & 0o077)
            or file_sha256(path) != record.get("sha256")
        ):
            raise ReleaseError("Backup bytes or private permissions changed")
        with path.open("rb") as stream:
            if stream.read(5) != b"PGDMP":
                raise ReleaseError("Backup is not a PostgreSQL custom archive")
        return path

    def write_receipt(self, name: str, record: dict[str, Any]) -> Path:
        if Path(name).name != name or not name.endswith(".json"):
            raise ReleaseError("Invalid exclusive release receipt name")
        path = self.directory / name
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        return path

    def migration_request(self, backup: dict[str, Any]) -> dict[str, Any]:
        current = self.checkpoint({SOURCE, CHAIN[-1]})
        self.verify_backup(backup)
        receipt = self.directory / (backup["filename"] + ".json")
        try:
            info = receipt.stat(follow_symlinks=False)
            valid = (
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and 0 < info.st_size <= 32768
                and not (os.name == "posix" and info.st_mode & 0o077)
                and json.loads(receipt.read_text(encoding="utf-8")) == backup
            )
        except (OSError, ValueError, UnicodeError):
            valid = False
        if not valid:
            raise ReleaseError("The original exclusive backup receipt is required")
        proof = {
            "bindings": asdict(self.bindings),
            "contract_sha256": self.contract_sha256,
            "backup_sha256": backup["sha256"],
            "backup_schema": SOURCE,
        }
        return {
            "already_at_target": current == CHAIN[-1],
            "image_id": self.bindings.image_id,
            "arguments": (
                "python",
                "scripts/apply_mcp_additive_upgrade.py",
                "--contract-json",
                json.dumps(self.contract, sort_keys=True, separators=(",", ":")),
            ),
            "environment": {
                "PGOPTIONS": PGOPTIONS,
                "MCP_RELEASE_PROOF_SHA256": digest_json(proof),
            },
            "timeout": 1800,
            "proof": proof,
            "retain_helper_container": True,
            "automatic_downgrade": False,
        }

    def verify_target(self, backup: dict[str, Any]) -> None:
        self.verify_backup(backup)
        self.checkpoint({CHAIN[-1]})
