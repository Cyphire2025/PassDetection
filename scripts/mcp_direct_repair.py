"""Retained ownership-only derivative of an exact already-built backend image.

The caller holds the release lock and drains/resumes workers. No application
container is stopped, started or removed here, and no production env is loaded.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import zlib
from urllib.parse import urlencode

from mcp_direct_build import (
    GIB,
    IMAGE,
    BuildError,
    RetainedBuild,
    command,
    contract_digest,
)
from mcp_direct_containers import LocalDocker
from mcp_direct_state import private_json

VALIDATE = r"""
import base64,hashlib,json,os,runpy,sys,traceback,zlib
from pathlib import Path
try:
    assert os.getuid()==1001 and os.getgid()==1001
    expected=json.loads(zlib.decompress(base64.b64decode(sys.argv[1])))
    root=Path('/app')
    for relative,digest in expected['files'].items():
        path=root/relative
        assert path.resolve().is_relative_to(root) and not path.is_symlink()
        assert path.stat().st_uid==1001 and path.stat().st_gid==1001
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
    migration=runpy.run_path('/app/scripts/apply_mcp_additive_upgrade.py')
    migration['verify_sources'](root,expected['migration_contract'])
    import mcp,pydantic
    assert mcp.__file__.startswith('/opt/mcp-deps/')
    assert pydantic.__file__.startswith('/opt/mcp-deps/')
    from scripts.export_api_contract import application_contract
    raw=(json.dumps(application_contract(),ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    assert hashlib.sha256(raw).hexdigest()==expected['api_contract_sha256']
except Exception as error:
    print('MCP_REPAIR_RUNTIME_FAILED',flush=True)
    print(json.dumps({'error_type':type(error).__name__,'frames':[
        {'file':Path(frame.filename).name,'line':frame.lineno}
        for frame in traceback.extract_tb(error.__traceback__)]}),flush=True)
    raise SystemExit(2) from None
print('MCP_REPAIR_RUNTIME_VERIFIED',flush=True)
"""


def _validation_payload(state, manifest: dict) -> tuple[str, str]:
    from release_mcp_contract import source_contract

    files = {
        name.removeprefix("backend/"): digest
        for name, digest in manifest["files"].items()
        if name.startswith(("backend/app/", "backend/alembic/", "backend/scripts/"))
        or name in {"backend/alembic.ini", "backend/gunicorn.conf.py"}
    }
    if not files or "scripts/apply_mcp_additive_upgrade.py" not in files:
        raise BuildError("repair_source_inventory_incomplete")
    contract_sha = contract_digest(
        (state.source / "backend/contracts/api.openapi.json").read_bytes()
    )
    payload = {
        "files": files,
        "api_contract_sha256": contract_sha,
        "migration_contract": source_contract(state.source),
    }
    encoded = base64.b64encode(
        zlib.compress(json.dumps(payload, sort_keys=True).encode())
    ).decode()
    if len(encoded) > 100000:
        raise BuildError("repair_validation_payload_exceeds_bound")
    return encoded, contract_sha


class OwnershipRepair(RetainedBuild):
    def create_helper(
        self,
        family: str,
        image: str,
        maximum: int,
        arguments: list[str],
        *,
        validation: bool,
    ) -> str:
        name = f"mcp-repair-{self.revision[:12]}-{self.output.name}-{family}"
        if self.existing(name):
            raise BuildError("retained_repair_helper_exists")
        self.capacity(maximum)
        args = [
            "docker",
            "create",
            "--name",
            name,
            "--memory",
            str(maximum),
            "--memory-swap",
            str(maximum),
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--network",
            "none",
            "--restart",
            "no",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--user",
            "1001:1001" if validation else "0:0",
            "--workdir",
            "/app",
            "--entrypoint",
            "/opt/venv/bin/python" if validation else "/bin/chown",
            "--label",
            f"globalconnects.direct_revision={self.revision}",
        ]
        if validation:
            args += [
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
                "--env",
                "PYTHONPATH=/opt/mcp-deps:/app",
                "--env",
                "PYTHONDONTWRITEBYTECODE=1",
                "--env",
                "APP_ENV=development",
                "--env",
                "APP_SECRET_KEY=contract-generation-only-not-for-deployment",
                "--env",
                "POSTGRES_PASSWORD=contract-only",
                "--env",
                "S3_ACCESS_KEY_ID=contract-only",
                "--env",
                "S3_SECRET_ACCESS_KEY=contract-only",
            ]
        else:
            args += ["--cap-add", "CHOWN"]
        identifier = self.run(*args, image, *arguments)
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise BuildError("invalid_repair_helper_identity")
        return identifier


def repair_backend_image(
    state, current_images: dict, output_label: str, *, run=command, client=None
) -> dict:
    """Produce images-<label>.json; every helper/image/failed attempt is retained."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,30}", output_label):
        raise BuildError("invalid_repair_output_label")
    manifest = state.verify_source()
    recorded = json.loads((state.directory / "images.json").read_text())
    if current_images != recorded or current_images.get("revision") != state.revision:
        raise BuildError("repair_image_receipt_changed")
    base_id = current_images["backend"]["image_id"]
    if not IMAGE.fullmatch(base_id):
        raise BuildError("repair_requires_immutable_image")
    original = json.loads(run("docker", "image", "inspect", base_id))[0]
    if (
        original["Id"] != base_id
        or original["Config"].get("User") != "1001:1001"
        or original["Config"].get("WorkingDir") != "/app"
        or original["Config"].get("Volumes")
        or original["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
        != state.revision
    ):
        raise BuildError("repair_original_image_binding_changed")
    encoded, contract_sha = _validation_payload(state, manifest)
    if current_images["backend"].get("verified_api_contract_sha256") != contract_sha:
        raise BuildError("repair_original_contract_binding_changed")
    receipt_path = state.directory / f"images-{output_label}.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise BuildError("repair_receipt_already_retained")
    output = state.directory / f"backend-repair-{output_label}"
    output.mkdir(mode=0o700)
    builder = OwnershipRepair(state.source, output, state.revision, run=run)
    identifier = builder.create_helper(
        "ownership", base_id, GIB // 4, ["-R", "1001:1001", "/app"], validation=False
    )
    state.event(
        "ownership-repair-helper-retained",
        container_id=identifier,
        source_image_id=base_id,
    )
    preparation = builder.execute(identifier, "ownership", GIB // 4)
    docker = client if client is not None else LocalDocker()
    # Full original image Config is supplied to commit: no root identity/chown
    # command, helper label, synthetic env, or validation flags enter the image.
    repaired_id = docker.request(
        "POST",
        "/commit?" + urlencode({"container": identifier, "pause": "false"}),
        copy.deepcopy(original["Config"]),
    )["Id"]
    if not IMAGE.fullmatch(repaired_id) or repaired_id == base_id:
        raise BuildError("invalid_repaired_image_identity")
    repaired = json.loads(run("docker", "image", "inspect", repaired_id))[0]
    if repaired["Id"] != repaired_id or repaired["Config"] != original["Config"]:
        raise BuildError("repair_runtime_image_config_changed")
    state.event(
        "ownership-repaired-image-retained",
        image_id=repaired_id,
        source_image_id=base_id,
    )
    validator = builder.create_helper(
        "validate", repaired_id, GIB, ["-c", VALIDATE, encoded], validation=True
    )
    state.event("ownership-validation-helper-retained", container_id=validator)
    validation = builder.execute(validator, "validation", GIB)
    if (
        "MCP_REPAIR_RUNTIME_VERIFIED"
        not in (output / "validation-build.log").read_text()
    ):
        raise BuildError("repair_validation_receipt_missing")
    result = copy.deepcopy(current_images)
    result["backend"].update(
        image_id=repaired_id,
        ownership_repair={
            "source_image_id": base_id,
            "preparation": preparation,
            "validation": validation,
            "runtime_uid": 1001,
            "runtime_gid": 1001,
            "validation_payload_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        },
    )
    private_json(receipt_path, result)
    state.event(
        "ownership-repair-qualified",
        filename=receipt_path.name,
        image_id=repaired_id,
        api_contract_sha256=contract_sha,
    )
    return result
