"""Private persistence, paid-call replay, bounded provider responses and upload rejection."""

import asyncio
import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from botocore.exceptions import ClientError
from pydantic import SecretStr

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.infrastructure.assistant.attachments import _office_text, prepare_attachment
from app.infrastructure.assistant.provider import OpenAIAssistantProvider
from app.infrastructure.assistant.store import AssistantStore
from app.infrastructure.security.upload_security import UploadSecurityContext


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def put_object(self, *, Key, Body, IfNoneMatch, **kwargs):
        assert IfNoneMatch == "*"
        if Key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
        self.objects[Key] = Body
        self.writes.append(Key)

    def get_object(self, *, Key, **kwargs):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        content = self.objects[Key]
        return {"Body": io.BytesIO(content), "ContentLength": len(content)}

    def list_objects_v2(self, *, Prefix, MaxKeys, ContinuationToken="0", **kwargs):
        keys = sorted(key for key in self.objects if key.startswith(Prefix))
        offset = int(ContinuationToken)
        return {
            "Contents": [{"Key": key} for key in keys[offset : offset + MaxKeys]],
            "NextContinuationToken": str(offset + MaxKeys)
            if len(keys) > offset + MaxKeys
            else None,
        }


@pytest.fixture
def stores():
    client = MemoryS3()
    storage = SimpleNamespace(
        _client=client, settings=SimpleNamespace(bucket_name="synthetic-private")
    )
    return AssistantStore(uuid4(), storage), AssistantStore(uuid4(), storage), client


async def test_private_owner_prefix_and_public_metadata_do_not_expose_file_text_or_storage(stores):
    owner, stranger, client = stores
    saved = await owner.save_asset(
        b"private attachment",
        name="Passengers.txt",
        mime="text/plain",
        kind="uploaded",
        text="Synthetic passenger information",
        prompt="Private prompt",
    )
    assert not {"text", "prompt", "storage_key", "prefix"} & saved.keys()
    assert await owner.content(saved["id"]) == b"private attachment"
    with pytest.raises(AssistantError, match="not in your workspace") as exc:
        await stranger.asset(saved["id"])
    assert exc.value.status == 404
    assert (await stranger.assets())["items"] == []
    assert len(client.writes) == 3  # immutable content, private metadata, chronological index


async def test_history_pages_are_newest_first_and_never_overwrite_completed_turns(stores):
    store, _, client = stores
    conversation = uuid4()
    identifiers = []
    for index in range(57):
        identifier = uuid4()
        identifiers.append(identifier)
        await store.save_turn(
            conversation,
            identifier,
            {
                "id": str(identifier),
                "assistant": str(index),
                "created_at": (
                    datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index)
                ).isoformat(),
            },
        )
    page = await store.turns(conversation)
    assert [int(row["assistant"]) for row in page["items"]] == list(range(56, 6, -1))
    earlier = await store.turns(conversation, page["next_cursor"])
    assert [int(row["assistant"]) for row in earlier["items"]] == list(range(6, -1, -1))
    before = dict(client.objects)
    with pytest.raises(AssistantError):
        await store.save_turn(
            conversation, identifiers[-1], {"id": str(identifiers[-1]), "assistant": "overwritten"}
        )
    assert client.objects == before


async def test_interrupted_paid_request_cannot_be_claimed_again_after_process_restart(stores):
    store, _, _ = stores
    conversation, request = uuid4(), uuid4()
    await store.claim_request(conversation, request, "body-fingerprint")
    restarted = AssistantStore(uuid4(), store.storage)
    restarted.prefix = store.prefix
    with pytest.raises(AssistantError) as exc:
        await restarted.claim_request(conversation, request, "body-fingerprint")
    assert exc.value.code == "request_interrupted"
    assert exc.value.status == 409


async def test_interrupted_index_is_repaired_without_resubmitting_provider_request(stores):
    store, _, client = stores
    conversation, request = uuid4(), uuid4()
    record = {
        "id": str(request),
        "created_at": datetime.now(UTC).isoformat(),
        "assistant": "Saved result",
    }
    await store._json(f"turns/{conversation}/{request}.json", record)
    assert await store.turn(conversation, request) == record
    assert (await store.turns(conversation))["items"] == [record]
    assert len(client.writes) == 2


def configured(**kwargs):
    return AssistantSettings(
        openai_api_key=SecretStr("synthetic-not-a-key"), _env_file=None, **kwargs
    )


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high", "xhigh", "max"])
async def test_luna_request_uses_selected_reasoning_and_streams_without_provider_storage(effort):
    received = []

    async def provider(request):
        assert str(request.url) == "https://api.openai.com/v1/responses"
        received.append(json.loads(request.content))
        content = 'data: {"type":"response.output_text.delta","delta":"Current records"}\n\n'
        content += 'data: {"type":"response.completed","response":{"output":[],"usage":{"input_tokens":12}}}\n\n'
        return httpx.Response(200, text=content)

    events = [
        item
        async for item in OpenAIAssistantProvider(
            configured(reasoning_effort=effort), httpx.MockTransport(provider)
        ).responses([], [], "Read only")
    ]
    assert events[0] == {"type": "delta", "text": "Current records"}
    assert received[0]["model"] == "gpt-6-luna"
    assert received[0]["reasoning"] == {"effort": effort}
    assert received[0]["store"] is False and received[0]["parallel_tool_calls"] is False


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401, text="sensitive-provider-message synthetic-not-a-key"),
        httpx.Response(
            200, text='data: {"type":"response.output_text.delta","delta":"Partial"}\n\n'
        ),
        httpx.Response(200, text="data: not-json\n\n"),
        httpx.Response(302, headers={"Location": "https://untrusted.example.test"}),
    ],
)
async def test_provider_errors_are_sanitized_and_partial_stream_is_not_success(response):
    provider = OpenAIAssistantProvider(configured(), httpx.MockTransport(lambda _: response))
    with pytest.raises(AssistantError) as exc:
        _ = [item async for item in provider.responses([], [], "Read only")]
    assert "synthetic-not-a-key" not in str(exc.value)
    assert "sensitive-provider" not in str(exc.value)


async def test_no_key_means_no_provider_call_or_accidental_reuse(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "belongs-to-another-feature")
    monkeypatch.delenv("AI_ASSISTANT_OPENAI_API_KEY", raising=False)
    transport = httpx.MockTransport(lambda _: pytest.fail("A live call was attempted"))
    provider = OpenAIAssistantProvider(AssistantSettings(_env_file=None), transport)
    with pytest.raises(AssistantError) as exc:
        await provider.images("Test", 1)
    assert exc.value.code == "setup_pending"


async def test_upload_rejects_oversize_and_executable_before_parsing():
    context = UploadSecurityContext(
        ingestion_flow="assistant_test", user_id=uuid4(), agency_id=None
    )
    for content, filename in [(b"x" * (8 * 1024 * 1024 + 1), "Large.txt"), (b"MZ", "program.exe")]:
        with pytest.raises(AssistantError) as exc:
            await prepare_attachment(content, filename, "application/octet-stream", context)
        assert exc.value.status in {413, 415}


@pytest.mark.parametrize(
    "name,content",
    [
        ("word/document.xml", b'<!DOCTYPE x [<!ENTITY x "bad">]><x>&x;</x>'),
        ("word/vbaProject.bin", b"macro"),
        ("too-big.xml", b"x" * (16 * 1024 * 1024 + 1)),
    ],
    ids=["active-xml", "macro", "zip-expansion"],
)
def test_office_archive_expansion_and_active_xml_are_rejected(name, content):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    with pytest.raises((ValueError, KeyError)):
        _office_text(output.getvalue(), ".docx")


async def test_stream_cancellation_does_not_wait_on_full_queue():
    from app.presentation.api.v1.routes.ai_assistant import _stream

    closed = asyncio.Event()

    async def events():
        try:
            for _ in range(100):
                yield {"type": "text_delta", "text": "test"}
        finally:
            closed.set()

    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    stream = _stream(events(), request)
    await anext(stream)
    await asyncio.sleep(0.01)
    await asyncio.wait_for(stream.aclose(), 0.5)
    assert closed.is_set()


async def test_voice_disconnect_closes_upstream_operation_promptly():
    from app.presentation.assistant.cancellation import client_bound

    closed = asyncio.Event()

    async def operation():
        try:
            await asyncio.sleep(10)
        finally:
            closed.set()

    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=True))
    with pytest.raises(AssistantError) as exc:
        await asyncio.wait_for(client_bound(request, operation()), 0.5)
    assert exc.value.code == "client_disconnected" and closed.is_set()


@pytest.mark.parametrize("mime,extension", [("audio/wav", "wav"), ("audio/mpeg", "mp3"), ("audio/mp4", "m4a"), ("audio/webm", "webm")])
async def test_transcription_uses_the_actual_audio_container(mime, extension):
    async def handler(request):
        assert f'filename="speech.{extension}"'.encode() in request.content
        return httpx.Response(200, json={"text":"Synthetic connection check"})
    provider = OpenAIAssistantProvider(configured(), httpx.MockTransport(handler))
    assert await provider.transcribe(b"synthetic-audio", mime) == "Synthetic connection check"
