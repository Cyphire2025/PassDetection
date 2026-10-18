"""Deleting a private chat cannot affect another owner, scope, library or business data."""

import asyncio
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.assistant.contracts import AssistantError
from app.infrastructure.assistant.store import AssistantStore
from tests.unit.infrastructure.test_assistant_boundaries import MemoryS3


class DeletableS3(MemoryS3):
    fail = False

    def list_objects_v2(self, **kwargs):
        # Force several batches, including the first-page-again deletion path.
        return super().list_objects_v2(**{**kwargs, "MaxKeys": min(kwargs["MaxKeys"], 2)})

    def delete_objects(self, *, Delete, **kwargs):
        if self.fail:
            return {"Errors": [{"Key": Delete["Objects"][0]["Key"], "Code": "AccessDenied"}]}
        for item in Delete["Objects"]:
            self.objects.pop(item["Key"], None)
        return {}

    def delete_object(self, *, Key, **kwargs):
        self.objects.pop(Key, None)


def saved_turn(identifier):
    return {"id": str(identifier), "created_at": datetime.now(UTC).isoformat(),
            "user": "Synthetic private question", "assistant": "Synthetic private answer"}


@pytest.fixture
def private_workspace():
    client = DeletableS3()
    storage = SimpleNamespace(_client=client, settings=SimpleNamespace(bucket_name="synthetic-private"))
    owner = uuid4()
    return AssistantStore(owner, storage), AssistantStore(uuid4(), storage), AssistantStore(owner, storage, scope="other-agency"), client


async def seed(store, conversation, count=1):
    await store.create_conversation(conversation, "Voice conversation")
    for _ in range(count):
        request = uuid4()
        await store.claim_request(conversation, request, "synthetic-fingerprint")
        await store.save_turn(conversation, request, saved_turn(request))


async def test_delete_purges_all_chat_copies_and_preserves_library_other_chats_owners_and_scopes(private_workspace):
    owner, stranger, other_scope, client = private_workspace
    selected, retained = uuid4(), uuid4()
    await seed(owner, selected, 7)
    await seed(owner, retained)
    await seed(stranger, selected)
    await seed(other_scope, selected)
    asset = await owner.save_asset(b"synthetic image", name="Saved image.png", mime="image/png", kind="generated")
    client.objects["business/passports/synthetic.json"] = b"untouched-business-data"
    untouched = {key: value for key, value in client.objects.items()
                 if str(selected) not in key or key.startswith(stranger.prefix) or key.startswith(other_scope.prefix)}
    await owner.delete_conversation(selected)
    assert [item["id"] for item in (await owner.conversations())["items"]] == [str(retained)]
    assert len((await owner.turns(retained))["items"]) == 1
    assert len((await stranger.turns(selected))["items"]) == 1
    assert len((await other_scope.turns(selected))["items"]) == 1
    assert await owner.content(asset["id"]) == b"synthetic image"
    assert all(client.objects[key] == value for key, value in untouched.items())
    assert [key for key in client.objects if key.startswith(owner.prefix) and str(selected) in key
            and not key.startswith(other_scope.prefix)] == [owner.prefix + f"deleted/{selected}.json"]
    await owner.delete_conversation(selected)  # Idempotent, including after removal of the thread index.


@pytest.mark.parametrize("operation", ["create", "claim", "save", "turn", "turns"])
async def test_deleted_chat_cannot_be_read_replayed_or_recreated(private_workspace, operation):
    owner, _, _, _ = private_workspace
    conversation, request = uuid4(), uuid4()
    await seed(owner, conversation)
    await owner.delete_conversation(conversation)
    operations = {
        "create": lambda: owner.create_conversation(conversation, "Recreated"),
        "claim": lambda: owner.claim_request(conversation, request, "new fingerprint"),
        "save": lambda: owner.save_turn(conversation, request, saved_turn(request)),
        "turn": lambda: owner.turn(conversation, request),
        "turns": lambda: owner.turns(conversation),
    }
    with pytest.raises(AssistantError) as error:
        await operations[operation]()
    assert error.value.code == "conversation_deleted" and error.value.status == 410


async def test_other_owner_and_scope_cannot_delete_a_chat(private_workspace):
    owner, stranger, other_scope, client = private_workspace
    conversation = uuid4()
    await seed(owner, conversation)
    before = dict(client.objects)
    for denied in (stranger, other_scope):
        with pytest.raises(AssistantError) as error:
            await denied.delete_conversation(conversation)
        assert error.value.status == 404
    assert client.objects == before


async def test_partial_delete_is_hidden_fails_closed_and_can_be_retried_after_restart(private_workspace):
    owner, _, _, client = private_workspace
    conversation = uuid4()
    await seed(owner, conversation)
    client.fail = True
    with pytest.raises(AssistantError) as error:
        await owner.delete_conversation(conversation)
    assert error.value.code == "deletion_incomplete"
    assert (await owner.conversations())["items"] == []
    with pytest.raises(AssistantError) as error:
        await owner.turns(conversation)
    assert error.value.status == 410
    client.fail = False
    restarted = AssistantStore(uuid4(), owner.storage)
    restarted.prefix = owner.prefix
    await restarted.delete_conversation(conversation)
    assert not any(key.startswith(owner.prefix + f"turns/{conversation}/") for key in client.objects)


async def test_inflight_message_cannot_resurrect_a_deleted_conversation(private_workspace, monkeypatch):
    owner, _, _, client = private_workspace
    conversation, request = uuid4(), uuid4()
    await seed(owner, conversation)
    started, finish = threading.Event(), threading.Event()
    original = client.put_object

    def delayed(**kwargs):
        if kwargs["Key"] == owner.prefix + f"turns/{conversation}/{request}.json":
            started.set()
            assert finish.wait(5)
        return original(**kwargs)

    monkeypatch.setattr(client, "put_object", delayed)
    saving = asyncio.create_task(owner.save_turn(conversation, request, saved_turn(request)))
    assert await asyncio.to_thread(started.wait, 3)
    try:
        await owner.delete_conversation(conversation)
    finally:
        finish.set()
    with pytest.raises(AssistantError) as error:
        await saving
    assert error.value.status == 410
    assert (await owner.conversations())["items"] == []
    assert [key for key in client.objects if str(conversation) in key] == [owner.prefix + f"deleted/{conversation}.json"]


async def test_history_listing_tolerates_concurrent_index_removal(private_workspace, monkeypatch):
    owner, _, _, _ = private_workspace
    conversation = uuid4()
    await seed(owner, conversation)
    original = owner._read

    async def deleting_read(suffix):
        if suffix.startswith("conversations/"):
            await owner.delete_conversation(conversation)
        return await original(suffix)

    monkeypatch.setattr(owner, "_read", deleting_read)
    assert (await owner.conversations())["items"] == []
