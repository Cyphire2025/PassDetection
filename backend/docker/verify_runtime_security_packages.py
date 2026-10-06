"""Check installed Debian security patches against the image's reviewed pins."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

PINS = Path(__file__).with_name("runtime_security_packages.json")


def verify_packages(pins: dict[str, str], installed: str) -> dict[str, str]:
    if not pins or any(not isinstance(name, str) or not isinstance(version, str)
                       or not name or not version for name, version in pins.items()):
        raise ValueError("Runtime security package pins are incomplete")
    found = {}
    for line in installed.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError("Cannot establish installed runtime security packages")
        name, version, status = fields
        if (name not in pins or name in found or version != pins[name]
                or status != "install ok installed"):
            raise ValueError("Runtime security package differs from the reviewed patch")
        found[name] = version
    if set(found) != set(pins):
        raise ValueError("Required runtime security package is missing")
    return found


def main() -> None:
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    installed = subprocess.check_output([
        "dpkg-query", "--show", "--showformat=${Package}\t${Version}\t${Status}\n", *pins,
    ], text=True)
    print(json.dumps({"debian_security_packages": verify_packages(pins, installed)}))


if __name__ == "__main__":
    main()
