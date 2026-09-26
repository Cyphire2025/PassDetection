"""Export, promote, verify and retrieve exact qualified images; never deploy.

GitHub CLI performs cryptographic verification against the reviewed repository,
workflow, main branch and exact source commit. There is no unsigned fallback.
Digest retrieval does not assert database rollback compatibility.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import tarfile
from collections.abc import Callable
from pathlib import Path

from registry_preflight import registry_tag_exists

ROOT = Path(__file__).resolve().parents[1]
TRUST = ROOT / "tooling/release-trust.json"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
REVISION = re.compile(r"[0-9a-f]{40}")
IMAGES = ("backend", "frontend")


def run(*args: str) -> str:
    return subprocess.check_output(args, text=True, encoding="utf-8").strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def trust_policy() -> dict:
    policy = json.loads(TRUST.read_text())
    if policy.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", policy["repository"]):
        raise ValueError("Invalid reviewed release trust policy")
    return policy


def dependency_policy_fingerprint(*, enforce_expiry: bool) -> str:
    from image_advisory_policy import validate_policy
    image_policy = json.loads((ROOT / "tooling/image-advisory-dispositions.json").read_text())
    python_policy = json.loads((ROOT / "tooling/dependency-exceptions.json").read_text())
    if enforce_expiry:
        today = dt.datetime.now(dt.timezone.utc).date()
        validate_policy(image_policy, today)
        for entry in python_policy["exceptions"]:
            reviewed, expires = (dt.date.fromisoformat(entry[key]) for key in ("reviewed_on", "expires_on"))
            if not reviewed <= today < expires or not 0 < (expires - reviewed).days <= 90:
                raise ValueError("Python advisory review expired or is future dated")
    return hashlib.sha256(json.dumps({"image": image_policy, "python": python_policy}, sort_keys=True).encode()).hexdigest()


def require_current_dependency_policy(manifest: dict) -> None:
    if manifest.get("dependency_policy_sha256") != dependency_policy_fingerprint(enforce_expiry=True):
        raise ValueError("Signed dependency policy differs from the currently reviewed checkout")


def verification_command(subject: str, revision: str, policy: dict, *, sbom: bool = False) -> list[str]:
    if not REVISION.fullmatch(revision):
        raise ValueError("A full source commit is required")
    command = ["gh", "attestation", "verify", subject, "--repo", policy["repository"],
               "--signer-workflow", f"{policy['repository']}/{policy['workflow']}",
               "--source-digest", revision, "--source-ref", policy["source_ref"],
               "--cert-oidc-issuer", policy["issuer"], "--deny-self-hosted-runners"]
    if sbom:
        command.extend(["--predicate-type", "https://spdx.dev/Document"])
    return command


def validate_manifest(manifest: dict, revision: str, policy: dict) -> None:
    if manifest.get("version") != 1 or manifest.get("revision") != revision or not REVISION.fullmatch(revision):
        raise ValueError("Release manifest does not match the requested source commit")
    if manifest.get("repository") != policy["repository"] or set(manifest.get("images", {})) != set(IMAGES):
        raise ValueError("Release manifest repository/image inventory differs from policy")
    for name, entry in manifest["images"].items():
        if not DIGEST.fullmatch(entry.get("digest", "")) or not DIGEST.fullmatch(entry.get("image_id", "")):
            raise ValueError("Release image requires immutable manifest and config digests")
        if entry.get("reference") != f"{policy['registry']}-{name}@{entry['digest']}":
            raise ValueError("Release image is outside the reviewed registry namespace")
    if not re.fullmatch(r"\d{4}_[a-z0-9_]+", manifest.get("schema", "")):
        raise ValueError("Release schema is missing")


def verify_manifest(path: Path, revision: str, *, pull: bool = False, enforce_current_policy: bool = False) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Release manifest must be a regular file")
    policy = trust_policy()
    # Verify bytes before interpreting attacker-controlled image names or schema.
    run(*verification_command(str(path), revision, policy))
    manifest = json.loads(path.read_text())
    validate_manifest(manifest, revision, policy)
    if enforce_current_policy:
        require_current_dependency_policy(manifest)
    for entry in manifest["images"].values():
        reference = entry["reference"]
        run(*verification_command(f"oci://{reference}", revision, policy))
        run(*verification_command(f"oci://{reference}", revision, policy, sbom=True))
        entry["local_image_id"] = verify_image_bytes(reference, entry["image_id"], revision, pull=pull)
    return manifest


def registry_config_identity(document: dict | list, image: dict) -> str:
    """Select the actual platform config, not a Docker-store-specific local ID."""
    entries = document if isinstance(document, list) else [document]
    candidates = []
    for entry in entries:
        platform = entry.get("Descriptor", {}).get("platform", {})
        if platform and (platform.get("os") != image["Os"] or platform.get("architecture") != image["Architecture"]):
            continue
        manifest = entry.get("OCIManifest") or entry.get("SchemaV2Manifest") or {}
        digest = manifest.get("config", {}).get("digest", "")
        if DIGEST.fullmatch(digest):
            candidates.append(digest)
    if len(candidates) != 1:
        raise ValueError("Registry must identify exactly one qualified platform config")
    return candidates[0]


def archive_config(archive: Path, reference: str) -> tuple[str, dict]:
    """Read Docker's config blob without extracting any archive paths."""
    with tarfile.open(archive, "r:") as contents:
        manifests = json.load(contents.extractfile("manifest.json"))
        matches = [item for item in manifests if reference in item.get("RepoTags", [])]
        if len(matches) != 1:
            raise ValueError("Qualified archive image inventory is ambiguous")
        member = contents.getmember(matches[0]["Config"])
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError("Unexpected image configuration member")
        raw = contents.extractfile(member).read()
        return "sha256:" + hashlib.sha256(raw).hexdigest(), json.loads(raw)


def validate_local_config(image: dict, config: dict) -> None:
    if (image.get("Config") != config.get("config")
            or image.get("RootFS", {}).get("Layers") != config.get("rootfs", {}).get("diff_ids")
            or image.get("Architecture") != config.get("architecture") or image.get("Os") != config.get("os")):
        raise ValueError("Local image config differs from qualified archive bytes")


def read_registry_manifest(reference: str) -> dict | list:
    return json.loads(run("docker", "manifest", "inspect", "--verbose", reference))


def verify_image_bytes(reference: str, image_id: str, revision: str, *, pull: bool,
                       manifest_reader: Callable[[str], dict | list] | None = None) -> str:
    """Transport/readback check, called only after provenance validation by the release path."""
    if "@" not in reference or not DIGEST.fullmatch(reference.rsplit("@", 1)[1]) or not DIGEST.fullmatch(image_id):
        raise ValueError("Image retrieval requires immutable digests")
    if pull:
        run("docker", "pull", reference)
    image = json.loads(run("docker", "image", "inspect", reference))[0]
    document = (manifest_reader or read_registry_manifest)(reference)
    if registry_config_identity(document, image) != image_id:
        raise ValueError("Retrieved image config differs from the qualified artifact")
    if reference not in image.get("RepoDigests", []):
        raise ValueError("Local image is not bound to the verified registry manifest digest")
    if (image.get("Config", {}).get("Labels") or {}).get("org.opencontainers.image.revision") != revision:
        raise ValueError("Image revision label differs from the signed source commit")
    return image["Id"]


def export_images(directory: Path, revision: str) -> None:
    if not REVISION.fullmatch(revision):
        raise ValueError("Full commit required")
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "revision": revision, "images": {},
                "dependency_policy_sha256": dependency_policy_fingerprint(enforce_expiry=True)}
    for name in IMAGES:
        reference = f"passdetection-{name}:ci"
        image = json.loads(run("docker", "image", "inspect", reference))[0]
        if (image["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") != revision:
            raise ValueError("Qualified image lacks the exact source revision label")
        archive = directory / f"{name}.tar"
        sbom = directory / f"{name}.spdx.json"
        if not sbom.is_file():
            raise ValueError("Full-image SBOM must be generated before export")
        if archive.exists():
            raise ValueError("Refusing to overwrite an existing qualified image archive")
        run("docker", "save", "--output", str(archive), reference)
        identifier, configuration = archive_config(archive, reference)
        validate_local_config(image, configuration)
        if name == "backend":
            receipt = json.loads((directory / "backend-advisory-conditions.json").read_text())
            current = json.loads((ROOT / "tooling/image-advisory-dispositions.json").read_text())
            if (receipt.get("result") != "passed" or receipt.get("image_config_sha256") != identifier
                    or receipt.get("policy_sha256") != hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()):
                raise ValueError("Qualified image lacks matching actual advisory-condition evidence")
        manifest["images"][name] = {"archive_sha256": sha256(archive), "image_id": identifier, "sbom_sha256": sha256(sbom)}
    (directory / "qualified-images.json").write_text(json.dumps(manifest, indent=2) + "\n")


def promote(directory: Path, revision: str, schema: str) -> dict:
    policy = trust_policy()
    # Verification is mandatory even though download-artifact validates its ZIP.
    index = directory / "qualified-images.json"
    run(*verification_command(str(index), revision, policy))
    qualified = json.loads(index.read_text())
    if qualified.get("revision") != revision or set(qualified.get("images", {})) != set(IMAGES):
        raise ValueError("Qualified archive index is incomplete or from a different commit")
    require_current_dependency_policy(qualified)
    result = {"version": 1, "revision": revision, "schema": schema,
              "repository": policy["repository"], "ci_run_id": os.environ.get("GITHUB_RUN_ID"), "images": {},
              "dependency_policy_sha256": qualified["dependency_policy_sha256"]}
    for name in IMAGES:
        archive = directory / f"{name}.tar"
        entry = qualified["images"][name]
        if sha256(archive) != entry.get("archive_sha256"):
            raise ValueError("Qualified image archive was changed")
        if sha256(directory / f"{name}.spdx.json") != entry.get("sbom_sha256"):
            raise ValueError("Qualified image SBOM was changed")
        run("docker", "load", "--input", str(archive))
        image = json.loads(run("docker", "image", "inspect", f"passdetection-{name}:ci"))[0]
        identifier, configuration = archive_config(archive, f"passdetection-{name}:ci")
        validate_local_config(image, configuration)
        if identifier != entry["image_id"]:
            raise ValueError("Loaded image differs from qualified image")
        destination = f"{policy['registry']}-{name}:{revision}"
        # Reject an existing revision tag before publication. This is a client
        # preflight, not a registry-side atomic tag lock; releases pin digests.
        exists = registry_tag_exists(destination)
        if exists:
            # Permit an interrupted promotion to resume only for identical bytes.
            run("docker", "pull", destination)
            existing = json.loads(run("docker", "image", "inspect", destination))[0]
            document = json.loads(run("docker", "manifest", "inspect", "--verbose", destination))
            if registry_config_identity(document, existing) != identifier:
                raise ValueError("Revision tag already refers to different bytes; never overwrite it")
        else:
            run("docker", "tag", image["Id"], destination)
            run("docker", "push", destination)
        run("docker", "pull", destination)
        published = json.loads(run("docker", "image", "inspect", destination))[0]
        repository = f"{policy['registry']}-{name}"
        references = [ref for ref in published.get("RepoDigests", []) if ref.startswith(repository + "@")]
        if len(references) != 1:
            raise ValueError("Registry readback differs from the qualified image")
        verify_image_bytes(references[0], identifier, revision, pull=False)
        result["images"][name] = {"reference": references[0], "digest": references[0].split("@", 1)[1], "image_id": identifier}
    validate_manifest(result, revision, policy)
    (directory / "release-artifacts.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "promote", "verify", "retrieve"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--schema")
    args = parser.parse_args()
    if not REVISION.fullmatch(args.revision):
        parser.error("A full 40-character commit is required")
    try:
        if args.mode == "export":
            export_images(args.directory, args.revision)
        elif args.mode == "promote":
            promote(args.directory, args.revision, args.schema or "")
        else:
            if args.mode == "retrieve":
                if args.directory.exists():
                    raise ValueError("Choose a new retrieval directory; existing artifacts are preserved")
                args.directory.mkdir(parents=True, mode=0o700)
                run("gh", "release", "download", f"release-{args.revision}", "--repo", trust_policy()["repository"],
                    "--pattern", "release-artifacts.json", "--dir", str(args.directory))
            verify_manifest(args.directory / "release-artifacts.json", args.revision, pull=True)
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.error(f"Artifact operation failed closed: {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
