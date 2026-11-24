"""Real PDF validation, private staging, ordering and replacement stay coherent."""

import io
import uuid

from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel as Profile,
)
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel as Document,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel as Access,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileSyncChangeModel,
)
from app.infrastructure.storage import minio_repository
from app.presentation.api.v1.routes.gc_app_content import router
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_gc_manager_response_durability import BASE, prepare_manager_command
from tests.integration.test_gc_manager_retained_assignments import enable_fk, group_access


async def test_document_upload_order_and_replacement_are_scoped_and_revisioned(
    auth_database, monkeypatch
):
    env = auth_database
    await enable_fk(env)
    env.app.include_router(router, prefix=BASE)
    _, original_headers, _ = await prepare_manager_command(env, "reinvite")
    headers = {
        key.decode(): value.decode() for key, value in original_headers if key != b"content-type"
    }
    async with env.sessions() as session, session.begin():
        profile = await session.scalar(select(Profile))
        group, access = await group_access(session, profile)
        group_id, access_id = group.id, access.id
    env.gate.release.set()
    objects = {}

    class StorageClient:
        def put_object(self, *, Key, Body, **_kwargs):
            objects[Key] = Body
            return {}

    storage = StorageClient()
    monkeypatch.setattr(minio_repository, "_shared_s3_clients", lambda: (storage, storage))
    with io.BytesIO() as stream, PdfWriter() as writer:
        writer.add_blank_page(width=144, height=144)
        writer.write(stream)
        pdf = stream.getvalue()
    path = f"{BASE}/groups/{group_id}/common-documents"
    async with AsyncClient(
        transport=ASGITransport(app=env.app), base_url="http://testserver", headers=headers
    ) as client:

        async def upload(revision, name, *, suffix="", payload=pdf):
            return await client.post(
                path + suffix,
                data={
                    "category": "travel_tips",
                    "display_name": name,
                    "expected_access_revision": revision,
                },
                files={"file": ("synthetic.pdf", payload, "application/pdf")},
            )

        first = await upload(1, "  First   guide ")
        assert first.status_code == 201, first.text
        assert first.json()["display_name"] == "First guide"
        second = await upload(2, "Second guide")
        assert second.status_code == 201, second.text
        first_id, second_id = first.json()["id"], second.json()["id"]
        listed = await client.get(path)
        assert listed.status_code == 200
        assert {item["id"] for item in listed.json()} == {first_id, second_id}
        assert "storage_key" not in listed.text and "gc-app/" not in listed.text
        ordered = await client.put(
            path + "/reorder",
            json={
                "ordered_document_ids": [second_id, first_id, second_id],
                "expected_access_revision": 3,
            },
        )
        assert ordered.status_code == 200, ordered.text
        assert [(item["id"], item["sort_order"]) for item in ordered.json()] == [
            (second_id, 0),
            (first_id, 1),
        ]
        stale = await client.put(
            path + "/reorder",
            json={"ordered_document_ids": [first_id], "expected_access_revision": 3},
        )
        assert stale.status_code == 409
        unavailable = await client.put(
            path + "/reorder",
            json={"ordered_document_ids": [str(uuid.uuid4())], "expected_access_revision": 4},
        )
        assert unavailable.status_code == 422
        replacement = await upload(4, "Updated first guide", suffix=f"/{first_id}/replace")
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["version"] == 2 and replacement.json()["sort_order"] == 1
        invalid = await upload(5, "Invalid", payload=b"not a PDF")
        assert invalid.status_code == 422
        cross_tenant = await client.get(path, params={"agency_id": str(uuid.uuid4())})
        assert cross_tenant.status_code == 403
    async with env.sessions() as session:
        saved = list(await session.scalars(select(Document)))
        original = next(item for item in saved if str(item.id) == first_id)
        replaced = next(item for item in saved if str(item.id) == replacement.json()["id"])
        assert len(saved) == len(objects) == 3
        assert original.logical_document_id == replaced.logical_document_id
        assert len({item.storage_key for item in saved}) == 3
        assert all(objects[item.storage_key] == pdf for item in saved)
        current = await session.get(Access, access_id)
        assert current.revision == 5 and current.common_document_version == 1
        changes = list(
            await session.scalars(
                select(MobileSyncChangeModel).where(
                    MobileSyncChangeModel.gc_group_access_id == access_id
                )
            )
        )
        assert len(changes) == 1 and changes[0].entity_type == "common_document_order"
