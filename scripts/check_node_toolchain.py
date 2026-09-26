"""Refuse unqualified dashboard Node/npm versions before installation/build."""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    policy = json.loads((ROOT / "tooling/toolchain.json").read_text())
    for tool in ("node", "npm"):
        executable = shutil.which(tool)
        if not executable:
            raise SystemExit(f"Missing {tool}; install the version in tooling/toolchain.json")
        actual = subprocess.check_output([executable, "--version"], text=True).strip().removeprefix("v")
        if actual != policy[tool]:
            raise SystemExit(f"Unsupported {tool} {actual}; use the reviewed {policy[tool]}")
    print("Dashboard developer Node/npm toolchain matches the reviewed pins")


if __name__ == "__main__":
    main()
