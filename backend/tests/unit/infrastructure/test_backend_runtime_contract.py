from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BACKEND = ROOT / "backend"


def test_backend_declares_only_the_verified_python_311_runtime() -> None:
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert pyproject["project"]["requires-python"] == ">=3.11,<3.12"
    assert (BACKEND / ".python-version").read_text(encoding="utf-8").strip() == "3.11"
    bases = re.findall(r"^FROM python:([^ ]+)", dockerfile, flags=re.MULTILINE)
    assert len(bases) >= 2
    assert len(set(bases)) == 1, "Builder and runtime must share the reviewed Python ABI/base"
    assert re.fullmatch(r"3\.11\.\d+-slim@sha256:[a-f0-9]{64}", bases[0])
    toolchain = json.loads((ROOT / "tooling/toolchain.json").read_text())
    versions = re.findall(r'python-version: "([^"]+)"', workflow)
    assert versions and set(versions) == {toolchain["python_bootstrap"]}


def test_runtime_direct_dependencies_and_build_tooling_are_exactly_pinned() -> None:
    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    requirements_lock = (BACKEND / "requirements.lock").read_text(encoding="utf-8")
    active_requirements = [
        line.split("#", 1)[0].strip()
        for line in requirements.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    assert active_requirements
    assert all("==" in requirement for requirement in active_requirements)
    assert pyproject["build-system"] == {
        "requires": ["setuptools==84.0.0", "wheel==0.48.0"],
        "build-backend": "setuptools.build_meta:__legacy__",
    }
    assert "--generate-hashes" in requirements_lock
    assert "--hash=sha256:" in requirements_lock

    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ARG PIP_VERSION=26.2.1" in dockerfile
    assert "pip install --no-cache-dir --require-hashes -r requirements.lock" in dockerfile
    developer_pins = (BACKEND / "requirements-dev.in").read_text()
    developer_lock = (BACKEND / "requirements-dev.lock").read_text()
    assert "--require-hashes -r requirements-dev.lock" in workflow
    for package in ("pip==26.2.1", "ruff==0.16.0", "uv==0.12.0", "pip-audit==2.10.1"):
        assert package in developer_pins
        assert package in developer_lock
    assert "--hash=sha256:" in developer_lock
