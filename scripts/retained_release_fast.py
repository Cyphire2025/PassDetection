"""Retained code-only image construction with the existing bounded builder."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from mcp_direct_build import GIB, BuildError, RetainedBuild, contract_digest


class FastBuild(RetainedBuild):
    """Code-only build: dependencies are inherited and must be unchanged."""

    def backend(self, base_image: str, previous_lock: Path | None = None) -> dict[str, Any]:
        if previous_lock is not None:
            try:
                unchanged = previous_lock.read_bytes().replace(b"\r\n", b"\n") == (
                    self.source / "backend/requirements.lock"
                ).read_bytes().replace(b"\r\n", b"\n")
            except OSError:
                raise BuildError("fast_build_dependency_lock_unavailable") from None
            if not unchanged:
                raise BuildError("fast_build_requires_unchanged_dependency_lock")
        expected = contract_digest(
            (self.source / "backend/contracts/api.openapi.json").read_bytes()
        )
        staging = "/retained-fast-source-" + uuid.uuid4().hex
        code = """
import hashlib,json,pathlib,shutil,subprocess
source=pathlib.Path(STAGING)
# docker cp nests into an existing directory. A fresh per-build destination
# prevents an inherited /candidate tree from silently supplying stale code.
assert not (source/'backend').exists(), 'nested_backend_staging_forbidden'
staged=(json.dumps(json.loads((source/'contracts/api.openapi.json').read_bytes()),ensure_ascii=False,sort_keys=True,indent=2)+'\\n').encode()
assert hashlib.sha256(staged).hexdigest()==EXPECTED, 'staged_contract_changed'
# The builder has CHOWN only: UID 0 cannot bypass the runtime owner's modes.
# Normalize just the disposable replacement paths before deleting or writing.
subprocess.run(['/bin/chown','0:0','/app'],check=True)
for name in ('app','alembic','scripts'):
 target=pathlib.Path('/app')/name
 if target.exists():
  subprocess.run(['/bin/chown','-R','0:0',str(target)],check=True)
  shutil.rmtree(target)
 shutil.copytree(source/name,target)
for name in ('alembic.ini','gunicorn.conf.py'):
 target=pathlib.Path('/app')/name
 if target.exists():subprocess.run(['/bin/chown','0:0',str(target)],check=True)
 shutil.copyfile(source/name,target)
subprocess.run(['/bin/chown','-R','1001:1001','/app'],check=True)
from scripts.export_api_contract import application_contract
raw=(json.dumps(application_contract(),ensure_ascii=False,sort_keys=True,indent=2)+'\\n').encode()
assert hashlib.sha256(raw).hexdigest()==EXPECTED
# Remove only this invocation's validated disposable input, never inherited
# staging directories or any retained container/image/release evidence.
subprocess.run(['/bin/chown','-R','0:0',str(source)],check=True)
shutil.rmtree(source)
""".replace("EXPECTED", repr(expected)).replace("STAGING", repr(staging))
        identifier = self.create(
            "backend",
            base_image,
            GIB,
            "/opt/venv/bin/python",
            ["-c", code],
            {"PYTHONPATH": "/opt/mcp-deps:/app"},
        )
        self.run(
            "docker", "cp", str(self.source / "backend"), f"{identifier}:{staging}", timeout=180
        )
        result = self.execute(identifier, "backend", GIB)
        return {
            **result,
            "image_id": self.commit_runtime(identifier, "backend"),
            "base_image_id": base_image,
            "verified_api_contract_sha256": expected,
        }


FastBuild.__module__ = "release_retained_update"
FastBuild.backend.__module__ = "release_retained_update"
