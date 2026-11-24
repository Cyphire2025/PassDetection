"""Background quiescence and fast-image preparation."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mcp_direct_state import WORKERS
from retained_release_contract import ORIGIN, require
from retained_release_fast import FastBuild
from retained_release_runtime import _RetainedRuntime


class _RetainedBuild(_RetainedRuntime):
    @contextmanager
    def background_quiescence(self) -> Iterator[None]:
        """Keep background capacity free until all bounded helpers have exited."""
        live = self.record["live"]
        # Stop scheduler first, prove workers idle, then free a bounded build budget.
        self.stop(live["email-beat"])
        try:
            self.idle_workers(live)
            for name in WORKERS:
                self.stop(live[name])
            yield
        finally:
            # A timed-out builder may still run. Do not overcommit or kill it.
            running = self.rows()
            require(
                not any(row["Id"] not in self.record["inventory"] for row in running),
                "builder_still_running_workers_not_resumed",
            )
            for name in (*WORKERS, "email-beat"):
                if live[name]["State"]["Running"]:
                    self.start(live[name])

    def build_fast_images(self) -> dict[str, Any]:
        live = self.record["live"]
        builder = FastBuild(
            self.source, self.directory, self.revision, schema_revision=self.candidate_schema
        )
        backend = builder.backend(live["backend"]["Image"])
        frontend = builder.frontend(live["frontend"]["Image"], ORIGIN)
        self.event("fast-images-built", fast_build={"backend": backend, "frontend": frontend})
        return {"backend": backend["image_id"], "frontend": frontend["image_id"]}

    def fast_images(self) -> dict[str, Any]:
        with self.background_quiescence():
            return self.build_fast_images()


# Preserve public method aliases and pickle identities through the compatibility facade.
for _name in ("background_quiescence", "build_fast_images", "fast_images"):
    _function = vars(_RetainedBuild)[_name]
    _function.__module__ = "release_retained_update"
    _function.__qualname__ = "RetainedUpdate." + _name
del _name, _function
