"""Run the declared synthetic workload and cross-tenant negative requests."""

from __future__ import annotations

import asyncio
import io
import random
import time
import uuid

import httpx
from PIL import Image
from workload_capacity_contract import ORIGIN, OVERLOAD_SECONDS
from workload_capacity_measurements import measured


def path_for(actor: dict, iteration: int) -> tuple[str, str]:
    return (
        ("stats", "/api/v1/dashboard/stats"),
        ("notifications", "/api/v1/notifications/feed?unread_only=false&limit=10"),
        (
            "roster",
            f"/api/v1/passports/groups/{actor['group_id']}/submissions-view?page_size=50&page=1",
        ),
        (
            "search",
            f"/api/v1/search?q=Traveller%20{actor['tenant']:02d}%2000001&limit=12",
        ),
        (
            "roster",
            f"/api/v1/passports/groups/{actor['group_id']}/submissions-view?page_size=50&page=2",
        ),
    )[iteration % 5]


async def paced_actor(
    client: httpx.AsyncClient,
    samples: list[dict],
    actor: dict,
    seconds: int,
    index: int,
) -> None:
    start = time.monotonic()
    await asyncio.sleep(index / 20)
    iteration = 0
    while time.monotonic() - start < seconds:
        operation, path = path_for(actor, iteration)
        await measured(client, samples, operation, "GET", path, actor=actor)
        iteration += 1
        await asyncio.sleep(max(0, start + iteration + index / 20 - time.monotonic()))


async def scans(client: httpx.AsyncClient, samples: list[dict], seed: dict, seconds: int) -> None:
    start = time.monotonic()
    for index in range(seconds):
        actor = seed["coordinators"][index % len(seed["coordinators"])]
        # Repeat each event once after the initial delivery, retaining the same
        # durable event identity so the API's idempotency is exercised under load.
        logical = index // 20
        await measured(
            client,
            samples,
            "scan",
            "POST",
            f"/api/v1/tour-operations/coordinator/sessions/{actor['session_id']}/scan",
            actor=actor,
            json={
                "qr_payload": actor["qr_payloads"][logical],
                "client_event_id": f"capacity-{seed['run_id']}-{index % 10}-{logical}",
                "sync_source": "online",
            },
        )
        await asyncio.sleep(max(0, start + index + 1 - time.monotonic()))


def synthetic_jpeg(run_id: str, page: int) -> bytes:
    # Different content for every page and run prevents scanner-cache hits from
    # being mistaken for sustained document-ingestion capacity.
    generator = random.Random(f"{run_id}-{page}")
    image = Image.frombytes("RGB", (1200, 800), generator.randbytes(1200 * 800 * 3))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


async def uploads(
    client: httpx.AsyncClient, samples: list[dict], seed: dict, pages: list[bytes]
) -> None:
    start = time.monotonic()
    # Four uploads/minute; two real ~0.8MB JPEG pages are scanned and persisted.
    # No OCR provider is required by the public cover-only configuration.
    for index in range(4):
        await asyncio.sleep(max(0, start + index * 15 - time.monotonic()))
        capability = uuid.uuid4().hex
        await measured(
            client,
            samples,
            "upload",
            "POST",
            f"/api/v1/passports/upload/{seed['groups'][index]['public_token']}",
            headers={"X-Upload-Session-ID": capability},
            data={
                "client_name": "Synthetic capacity upload",
                "acquisition_mode": "file",
                "upload_idempotency_key": capability,
            },
            files={
                "passport_cover_file": (
                    "synthetic-front.jpg",
                    pages[index * 2],
                    "image/jpeg",
                ),
                "passport_back_cover_file": (
                    "synthetic-back.jpg",
                    pages[index * 2 + 1],
                    "image/jpeg",
                ),
            },
        )


async def overload_actor(client: httpx.AsyncClient, samples: list[dict], actor: dict) -> None:
    stop = time.monotonic() + OVERLOAD_SECONDS
    while time.monotonic() < stop:
        await measured(
            client,
            samples,
            "stats",
            "GET",
            "/api/v1/dashboard/stats",
            actor=actor,
            overload=True,
        )


async def tenant_negatives(client: httpx.AsyncClient, seed: dict) -> None:
    for actor in seed["actors"]:
        other = seed["groups"][(actor["tenant"] + 1) % 10]
        headers = {"Cookie": f"access_token={actor['token']}", "Origin": ORIGIN}
        search = await client.get(
            f"/api/v1/search?q=Traveller%20{other['tenant']:02d}%2000001",
            headers=headers,
        )
        if search.status_code != 200 or search.json() != []:
            raise RuntimeError("Cross-tenant search exposed a seeded foreign passenger")
        roster = await client.get(
            f"/api/v1/passports/groups/{other['group_id']}/submissions-view",
            headers=headers,
        )
        if (
            roster.status_code != 200
            or roster.json()["items"] != []
            or roster.json()["group_total"] != 0
        ):
            raise RuntimeError(
                "Cross-tenant roster boundary did not return an empty authorized set"
            )


# Preserve the original QA import and pickle identities through its facade.
for _export in (
    path_for,
    paced_actor,
    scans,
    synthetic_jpeg,
    uploads,
    overload_actor,
    tenant_negatives,
):
    _export.__module__ = "qualify_workload_capacity"
del _export
