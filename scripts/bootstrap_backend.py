"""Create a new supported backend environment with hash-verified development tools.

Windows: py -3.11 scripts/bootstrap_backend.py
POSIX: python3.11 scripts/bootstrap_backend.py
Existing environments are never deleted, replaced, or silently reused.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def require_supported_python(version: tuple[int, ...]) -> None:
    if version[:2] != (3, 11):
        raise ValueError("CPython 3.11 is required; select py -3.11 or python3.11 explicitly")


def environment_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "backend/.venv")
    parser.add_argument("--check", action="store_true", help="Validate this interpreter and tools only")
    args = parser.parse_args()
    try:
        require_supported_python(sys.version_info)
        if sys.implementation.name != "cpython":
            raise ValueError("Only CPython is qualified")
        if args.check:
            pins = {}
            for line in (ROOT / "backend/requirements-dev.in").read_text().splitlines():
                if "==" in line and not line.startswith("#"):
                    package, expected = line.split("==", 1)
                    actual = importlib.metadata.version(package)
                    if actual != expected:
                        raise ValueError(f"{package} differs from the reviewed development toolchain")
                    pins[package] = actual
            print(json.dumps({"python": sys.version.split()[0], "tools": pins}, indent=2))
            return 0
        target = args.directory.resolve()
        if target.exists():
            raise ValueError("Target exists; choose a new environment directory (nothing was removed)")
        if not (ROOT / "backend/requirements-dev.lock").is_file():
            raise ValueError("The reviewed development lock is missing")
        venv.EnvBuilder(with_pip=True).create(target)
        python = str(environment_python(target))
        subprocess.run([python, "-m", "pip", "install", "--require-hashes", "-r",
                        str(ROOT / "backend/requirements-dev.lock")], check=True)
        subprocess.run([python, str(Path(__file__).resolve()), "--check"], check=True)
        print(f"Ready: {python}")
        return 0
    except (ValueError, importlib.metadata.PackageNotFoundError) as error:
        parser.error(str(error))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
