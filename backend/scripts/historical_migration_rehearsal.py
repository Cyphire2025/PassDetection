"""Disposable migration tree for testing a historical image's exact head guard.

Production helpers are unchanged. Only synthetic rehearsal subprocesses point
their helper ROOT at this temporary copy of the selected ancestor migrations.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


@contextmanager
def historical_tree(backend: Path, target: str) -> Iterator[Path]:
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    source = ScriptDirectory.from_config(config)
    selected = list(source.iterate_revisions(target, "base"))
    with tempfile.TemporaryDirectory(prefix="passdetection-ci-historical-migrations-") as temporary:
        root = Path(temporary)
        versions = root / "alembic/versions"
        versions.mkdir(parents=True)
        shutil.copyfile(backend / "alembic.ini", root / "alembic.ini")
        shutil.copyfile(backend / "alembic/env.py", root / "alembic/env.py")
        for revision in selected:
            path = Path(revision.path)
            if path.is_symlink() or not path.resolve().is_relative_to((backend / "alembic/versions").resolve()):
                raise ValueError("regular_owned_migration_source_required")
            shutil.copyfile(path, versions / path.name)
        historical = Config(str(root / "alembic.ini"))
        historical.set_main_option("script_location", str(root / "alembic"))
        if ScriptDirectory.from_config(historical).get_heads() != [target]:
            raise ValueError("exact_historical_migration_head_required")
        yield root
