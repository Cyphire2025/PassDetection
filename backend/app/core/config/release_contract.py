"""Reviewed release contract packaged with the runtime image."""

import json
from pathlib import Path

_manifest = json.loads(Path(__file__).with_name("release_manifest.json").read_text(encoding="utf-8"))
SCHEMA_REVISION: str = _manifest["schema_revision"]
