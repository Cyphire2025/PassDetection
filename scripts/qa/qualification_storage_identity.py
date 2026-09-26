"""Write only synthetic QA credentials for the pinned provider's runtime UID.

The Seaweed entrypoint drops root to its seaweed account. A Linux runner's
0600 file must therefore change ownership without making credentials public.
Atomic replacement lets that runner repeat setup without reading a file now
owned by the provider. Production identity provisioning is separate.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OWNERSHIP_SCRIPT = 'chown "$(id -u seaweed):$(id -g seaweed)" /identity.json && chmod 0600 /identity.json'


def write_qualification_identity(path: Path, document: str, image: str) -> None:
    if not re.fullmatch(r"chrislusf/seaweedfs:[A-Za-z0-9_.-]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("Synthetic identity requires an immutable SeaweedFS image")
    path = path.absolute()
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Synthetic identity destination must be a regular file")
    # A runner-owned directory permits replacing a provider-owned file on retry;
    # a file directly in sticky /tmp would not be replaceable by that runner.
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    staging = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(document)
        staging.chmod(0o600)
        if sys.platform == "linux":
            subprocess.run([
                "docker", "run", "--rm", "--network", "none", "--user", "0:0",
                "--mount", f"type=bind,source={staging},target=/identity.json",
                "--entrypoint", "/bin/sh", image, "-ec", OWNERSHIP_SCRIPT,
            ], check=True, timeout=120, stdout=subprocess.DEVNULL)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)
