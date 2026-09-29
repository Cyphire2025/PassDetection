"""Package and verify the Windows connector against one qualified source commit.

The signed inventory binds wheel, runtime lock and installation instructions.
It does not claim a successful interactive Codex sign-in or OS-vault exercise.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

import tomllib

from release_artifacts import run, trust_policy, verification_command

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "connector-artifacts.json"
REVISION = re.compile(r"[0-9a-f]{40}")


def source_files(root: Path) -> dict[str, Path]:
    project = tomllib.loads((root / "mcp-connector/pyproject.toml").read_text("utf-8"))["project"]
    version = project["version"]
    if (project["name"] != "global-connects-mcp-connector"
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)
            or project["requires-python"] != ">=3.11,<3.12"):
        raise ValueError("Connector packaging contract changed")
    wheel = f"global_connects_mcp_connector-{version}-py3-none-any.whl"
    return {wheel: root / "mcp-connector/dist" / wheel,
            "connector-requirements.lock": root / "mcp-connector/requirements.lock",
            "connector-README.md": root / "mcp-connector/README.md"}


def digest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("Connector asset must be a bounded regular file")
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"sha256": checksum, "size_bytes": path.stat().st_size}


def package(directory: Path, revision: str, root: Path = ROOT) -> dict:
    if not REVISION.fullmatch(revision):
        raise ValueError("A full source commit is required")
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, source in source_files(root).items():
        entry = digest(source)
        destination = directory / name
        if destination.exists() or destination.is_symlink():
            raise ValueError("Refusing to replace a retained connector asset")
        shutil.copyfile(source, destination)
        if digest(destination) != entry:
            raise ValueError("Connector copy checksum mismatch")
        files[name] = entry
    manifest = {"version": 1, "revision": revision, "platform": "windows",
                "python": "3.11", "files": files,
                "interactive_sign_in_qualified": False}
    with (directory / MANIFEST).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_bytes(directory: Path, revision: str, root: Path = ROOT) -> dict:
    path = directory / MANIFEST
    digest(path)
    manifest = json.loads(path.read_text("utf-8"))
    if (not isinstance(manifest, dict) or set(manifest) != {
            "version", "revision", "platform", "python", "files", "interactive_sign_in_qualified"}
            or type(manifest["version"]) is not int or manifest["version"] != 1
            or not REVISION.fullmatch(revision) or manifest["revision"] != revision
            or manifest["platform"] != "windows" or manifest["python"] != "3.11"
            or manifest["interactive_sign_in_qualified"] is not False
            or not isinstance(manifest["files"], dict)):
        raise ValueError("Connector inventory differs from the reviewed release contract")
    expected = source_files(root)
    if set(manifest["files"]) != set(expected):
        raise ValueError("Connector asset names differ from the source package")
    for name, entry in manifest["files"].items():
        if (not isinstance(entry, dict) or set(entry) != {"sha256", "size_bytes"}
                or type(entry["size_bytes"]) is not int or digest(directory / name) != entry):
            raise ValueError("Connector asset checksum or size mismatch")
        if not name.endswith(".whl") and digest(expected[name]) != entry:
            raise ValueError("Connector instructions/runtime lock differ from the source commit")
    return manifest


def verify(directory: Path, revision: str) -> dict:
    # Authenticate bytes before interpreting asset names. The source digest and
    # reviewed main workflow are checked by the same policy as image promotion.
    digest(directory / MANIFEST)
    run(*verification_command(str(directory / MANIFEST), revision, trust_policy()))
    return verify_bytes(directory, revision)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("package", "verify"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "package":
        package(args.directory, args.revision)
    else:
        verify(args.directory, args.revision)
    print(f"Connector {args.action} passed for source {args.revision}; interactive sign-in remains unqualified.")


if __name__ == "__main__":
    main()
