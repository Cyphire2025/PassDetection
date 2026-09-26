"""Inventory the installed npm CLI itself, including its bundled dependencies.

A directory scan is not accepted as evidence that these installer packages were
catalogued. Feed this nonempty, version-checked PURL inventory to Grype explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def inventory(directory: Path, expected_version: str) -> dict[str, dict[str, str]]:
    directory = directory.resolve(strict=True)
    main = json.loads((directory / "package.json").read_text(encoding="utf-8-sig"))
    if main.get("name") != "npm" or main.get("version") != expected_version:
        raise ValueError("The installed npm package differs from the reviewed toolchain")
    packages = {}
    for path in sorted(directory.rglob("package.json")):
        if not path.resolve().is_relative_to(directory):
            raise ValueError("Installed toolchain metadata escapes its reviewed package directory")
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        name, version = data.get("name"), data.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        purl = f"pkg:npm/{quote(name, safe='/')}@{quote(version, safe='.')}"
        packages[purl] = {"name": name, "version": version, "path": path.relative_to(directory).as_posix(),
                          "metadata_sha256": hashlib.sha256(raw).hexdigest()}
    names = {item["name"] for item in packages.values()}
    if len(packages) < 100 or not {"npm", "tar", "pacote", "undici", "brace-expansion", "ip-address"} <= names:
        raise ValueError("Installer inventory is incomplete; refusing an empty or partial vulnerability gate")
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--npm-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    expected = json.loads((ROOT / "tooling/toolchain.json").read_text())["npm"]
    packages = inventory(args.npm_root, expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(sorted(packages)) + "\n")
    args.output.with_suffix(".json").write_text(json.dumps(packages, indent=2) + "\n")
    print(f"Inventoried {len(packages)} installed npm {expected} package/version pairs")


if __name__ == "__main__":
    main()
