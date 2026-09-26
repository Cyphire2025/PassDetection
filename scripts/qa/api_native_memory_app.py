"""Network-isolated QA routes; never included in the production application."""
from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from fastapi import FastAPI, Request

# Load the full real API dependency graph into every Gunicorn worker. Only
# lifespan/dependency I/O is excluded; image transforms and HTTP handling are real.
if __name__ != "__main__":
    from app.infrastructure.imaging.passport_image_cropper import (
        render_passport_image_crop,
    )
    from app.main import app as imported_application
    from app.presentation.middleware.error_handler import register_exception_handlers

assert os.environ.get("POSTGRES_DB") == "passdetection_ci_memory"
assert os.environ.get("APP_ENV") == "development"
app = FastAPI()
if __name__ != "__main__":
    assert imported_application is not None
    register_exception_handlers(app)


@app.get("/ready")
async def ready():
    return {"pid": os.getpid()}


@app.post("/crop")
async def crop(request: Request):
    content = await request.body()
    assert len(content) == 10 * 1024 * 1024
    assert hashlib.sha256(content).hexdigest() == Path("/fixtures/input.sha256").read_text().strip()
    result = await asyncio.to_thread(
        render_passport_image_crop, content, x=0, y=0, width=1, height=1,
        rotation_degrees=45, sharpness=3, sharpness_algorithm_version=2,
    )
    return {"pid": os.getpid(), "source_width": result.source_width,
            "source_height": result.source_height, "output_width": result.output_width,
            "output_height": result.output_height, "bytes": len(result.content),
            "sha256": hashlib.sha256(result.content).hexdigest()}


def client_probe():
    """Run from docker exec in the same isolated container; account its memory too."""
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    source = Path("/fixtures/input.png").read_bytes()
    cgroup = Path("/sys/fs/cgroup")

    def sample():
        return {"current": int((cgroup / "memory.current").read_text()),
                "peak": int((cgroup / "memory.peak").read_text()),
                "events": dict(line.split() for line in (cgroup / "memory.events").read_text().splitlines()),
                "kernel_oom_kills": int(dict(line.split() for line in Path("/proc/vmstat").read_text().splitlines())["oom_kill"]),
                "rss_by_pid": {path.parent.name: [line for line in path.read_text().splitlines() if line.startswith(("Name:", "VmRSS:", "RssAnon:"))]
                               for path in Path("/proc").glob("[0-9]*/status") if path.exists()}}

    def request_crop(_):
        started = time.monotonic()
        with httpx.Client(timeout=60, trust_env=False) as client:
            response = client.post("http://127.0.0.1:8000/crop", content=source)
        body = response.json()
        assert response.status_code in {200, 503}, body
        if response.status_code == 503:
            assert response.headers["retry-after"] == "5"
            assert body["error"]["code"] == "IMAGE_PROCESSING_BUSY"
        else:
            # Crop metadata describes the expanded, rotated source canvas.
            assert body["source_width"] == body["output_width"] >= 7000, body
            assert body["source_height"] == body["output_height"] >= 7000, body
        row = {"status": response.status_code, "seconds": time.monotonic() - started, "body": body}
        print(json.dumps({"checkpoint": "response", "response": row, "memory": sample()}), flush=True)
        return row

    initial = sample()
    print(json.dumps({"checkpoint": "initial", "memory": initial}), flush=True)
    rounds = []
    for count in (4, 8, 8):
        print(json.dumps({"checkpoint": "round", "concurrency": count}), flush=True)
        with ThreadPoolExecutor(max_workers=count) as workers:
            responses = list(workers.map(request_crop, range(count)))
        retries = [request_crop(index) for index, row in enumerate(responses) if row["status"] == 503]
        assert all(row["status"] == 200 for row in retries)
        assert any(row["status"] == 200 for row in responses)
        assert len({row["body"]["sha256"] for row in [*responses, *retries] if row["status"] == 200}) == 1
        rounds.append({"concurrency": count, "responses": responses, "explicit_retries": retries, "memory": sample()})
    final = sample()
    assert final["events"]["oom"] == final["events"]["oom_kill"] == "0"
    print(json.dumps({"initial": initial, "rounds": rounds, "final": final}), flush=True)


if __name__ == "__main__":
    client_probe()
