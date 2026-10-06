"""Create a release or reuse exactly matching retained assets; never replace them.

The caller has already qualified and promoted images. Authenticate both local
inventories again before publication, then bind GitHub's tag and every downloaded
asset to those exact bytes. Partial or changed existing releases fail closed.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

from release_artifacts import (
    REVISION,
    run,
    sha256,
    trust_policy,
    validate_manifest,
    verification_command,
)
from release_connector import verify as verify_connector

MAX_ASSET_BYTES = 128 * 1024 * 1024
NOTES = ("Qualified immutable images, Windows connector and signed inventories. No deployment was performed. "
         "Interactive Codex sign-in remains a separate acceptance gate.")


def asset_digest(path: Path) -> tuple[int, str]:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_ASSET_BYTES:
        raise ValueError("Release asset must be a bounded regular file")
    return path.stat().st_size, sha256(path)


def verified_assets(images: Path, connector: Path, revision: str) -> dict[str, Path]:
    policy = trust_policy()
    manifest_path = images / "release-artifacts.json"
    asset_digest(manifest_path)
    run(*verification_command(str(manifest_path), revision, policy))
    validate_manifest(json.loads(manifest_path.read_text("utf-8")), revision, policy)
    connector_inventory = verify_connector(connector, revision)
    assets = {name: images / name for name in ("release-artifacts.json", "backend.spdx.json", "frontend.spdx.json")}
    assets.update({name: connector / name for name in ("connector-artifacts.json", *connector_inventory["files"])})
    for path in assets.values():
        asset_digest(path)
    return assets


class GitHub:
    def __init__(self, repository: str):
        self.repository = repository
        self.prefix = f"repos/{repository}/"

    def metadata(self, endpoint: str) -> dict | None:
        result = subprocess.run(
            ["gh", "api", "--hostname", "github.com", "--include", self.prefix + endpoint],
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        )
        headers, separator, body = result.stdout.replace("\r\n", "\n").partition("\n\n")
        status = re.match(r"HTTP/\S+ (\d{3})(?:\s|$)", headers)
        if not separator or status is None:
            raise ValueError("Cannot establish GitHub release state")
        if status[1] == "404":
            return None
        if result.returncode or status[1] != "200":
            raise ValueError("GitHub release lookup failed; publication stopped")
        value = json.loads(body)
        if not isinstance(value, dict):
            raise TypeError("Invalid GitHub release metadata")
        return value

    def require_tag(self, tag: str, revision: str, *, allow_missing: bool = False) -> None:
        reference = self.metadata("git/ref/tags/" + tag)
        if reference is None:
            if allow_missing:
                return
            raise ValueError("Release tag is missing")
        if reference.get("ref") != "refs/tags/" + tag:
            raise ValueError("Release tag identity differs")
        target = reference.get("object", {})
        for _ in range(5):
            if target.get("type") == "commit" and target.get("sha") == revision:
                return
            if target.get("type") != "tag" or REVISION.fullmatch(target.get("sha", "")) is None:
                break
            annotated = self.metadata("git/tags/" + target["sha"])
            if annotated is None or annotated.get("sha") != target["sha"]:
                break
            target = annotated.get("object", {})
        raise ValueError("Release tag does not resolve to the selected commit")

    def verify_assets(self, release: dict, tag: str, assets: dict[str, Path]) -> None:
        if release.get("tag_name") != tag or release.get("draft") is not False:
            raise ValueError("Existing release identity or publication state differs")
        entries = release.get("assets")
        if (not isinstance(entries, list) or len(entries) != len(assets)
                or {entry.get("name") for entry in entries} != set(assets)):
            raise ValueError("Existing release asset inventory is missing or differs")
        with tempfile.TemporaryDirectory(prefix="release-asset-readback-") as directory:
            for entry in entries:
                expected = asset_digest(assets[entry["name"]])
                identifier = entry.get("id")
                if (type(identifier) is not int or identifier <= 0 or entry.get("state") != "uploaded"
                        or type(entry.get("size")) is not int or entry["size"] != expected[0]):
                    raise ValueError("Existing release asset identity or size differs")
                downloaded = Path(directory) / str(identifier)
                with downloaded.open("xb") as output:
                    result = subprocess.run(
                        ["gh", "api", "--hostname", "github.com", self.prefix + f"releases/assets/{identifier}",
                         "--header", "Accept: application/octet-stream"],
                        stdout=output, stderr=subprocess.PIPE, timeout=120, check=False,
                    )
                if result.returncode or asset_digest(downloaded) != expected:
                    raise ValueError("Existing release asset bytes differ; retained assets were not changed")

    def create(self, tag: str, revision: str, assets: dict[str, Path]) -> None:
        run("gh", "release", "create", tag, "--repo", self.repository, "--target", revision,
            "--title", f"Qualified artifacts {revision}", "--notes", NOTES,
            *(str(path) for path in assets.values()))


def publish(images: Path, connector: Path, revision: str) -> str:
    if REVISION.fullmatch(revision) is None:
        raise ValueError("A full source commit is required")
    assets = verified_assets(images, connector, revision)
    github = GitHub(trust_policy()["repository"])
    tag = "release-" + revision
    existing = github.metadata("releases/tags/" + tag)
    github.require_tag(tag, revision, allow_missing=existing is None)
    if existing is not None:
        github.verify_assets(existing, tag, assets)
        github.require_tag(tag, revision)
        return "reused"
    # If creation/upload has an unknown or partial outcome, retain it and stop.
    # Never retry with --clobber, delete assets, or move a previously created tag.
    github.create(tag, revision, assets)
    created = github.metadata("releases/tags/" + tag)
    if created is None:
        raise ValueError("Created release could not be read back")
    github.require_tag(tag, revision)
    github.verify_assets(created, tag, assets)
    github.require_tag(tag, revision)
    return "created"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--connector", type=Path, required=True)
    args = parser.parse_args()
    result = publish(args.images, args.connector, args.revision)
    print(f"Release {result}: exact tag, signed inventories, and all retained asset bytes verified")


if __name__ == "__main__":
    main()
