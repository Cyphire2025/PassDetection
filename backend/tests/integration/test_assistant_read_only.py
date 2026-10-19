"""Synthetic SQL data through the actual first-party reader and streamed tool loop."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from pydantic import SecretStr
from sqlalchemy import select, update

from app.application.assistant.contracts import AssistantError, ChatRequest
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.assistant.store import AssistantStore
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.assistant import chat, reads
from app.presentation.mcp.observational_session import NonObservationalDashboardRead
from tests.unit.infrastructure.test_assistant_boundaries import MemoryS3


@pytest.fixture
async def workspace(db_session, monkeypatch):
    user = UserModel(
        id=uuid4(),
        email="assistant-reader@example.test",
        hashed_password="fixture-only",
        full_name="Assistant fixture",
        role="super_admin",
        is_active=True,
    )
    agency = AgencyModel(id=uuid4(), name="Synthetic agency", email="agency@example.test")
    other = AgencyModel(id=uuid4(), name="Other agency", email="other@example.test")
    db_session.add_all([user, agency, other])
    await db_session.flush()
    group = ClientGroupModel(
        id=uuid4(), agency_id=agency.id, name="Synthetic departure", token="protected-upload-token"
    )
    db_session.add(group)
    await db_session.commit()
    actor = await UserRepository(db_session).get_by_id(user.id)

    @asynccontextmanager
    async def session_factory():
        yield db_session

    monkeypatch.setattr(reads, "AsyncSessionFactory", session_factory)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/ai-assistant/chat",
            "headers": [],
            "query_string": b"",
            "app": FastAPI(),
            "client": ("127.0.0.1", 0),
        }
    )
    store = AssistantStore(
        actor.id,
        SimpleNamespace(_client=MemoryS3(), settings=SimpleNamespace(bucket_name="fixture")),
    )
    return db_session, actor, agency, other, group, request, store


async def test_first_party_read_is_current_redacted_and_rejects_wrong_agency(workspace):
    session, actor, agency, other, group, request, _ = workspace
    reader = reads.DashboardReader(request, actor)
    first = await reader.read(
        "group_details", {"group_id": str(group.id)}, agency_id=str(agency.id)
    )
    assert "Synthetic departure" in json.dumps(first)
    assert "protected-upload-token" not in json.dumps(first)
    await session.execute(
        update(ClientGroupModel)
        .where(ClientGroupModel.id == group.id)
        .values(name="Updated departure")
    )
    await session.commit()
    second = await reader.read(
        "group_details", {"group_id": str(group.id)}, agency_id=str(agency.id)
    )
    assert "Updated departure" in json.dumps(second)
    assert second["observed_at"] >= first["observed_at"]
    with pytest.raises(AssistantError) as exc:
        await reader.read("group_details", {"group_id": str(group.id)}, agency_id=str(other.id))
    assert exc.value.code == "scope_mismatch"


async def test_role_restriction_and_live_revocation_are_enforced(workspace):
    session, actor, _, _, _, _, _ = workspace
    with pytest.raises(AssistantError):
        await reads.fresh_actor(
            replace(actor, role=UserRole.AGENCY_ADMIN, actual_role=UserRole.SUPER_ADMIN)
        )
    await session.execute(update(UserModel).where(UserModel.id == actor.id).values(is_active=False))
    await session.commit()
    with pytest.raises(AssistantError) as exc:
        await reads.fresh_actor(actor)
    assert exc.value.status == 403


async def test_regressing_reader_cannot_change_business_rows_or_commit(workspace, monkeypatch):
    session, actor, agency, _, group, request, _ = workspace

    async def bad_reader(group_id, current_user, session):
        await session.execute(
            update(ClientGroupModel)
            .where(ClientGroupModel.id == group_id)
            .values(name="Forbidden mutation")
        )
        await session.commit()

    monkeypatch.setattr(reads, "dashboard_handler", lambda _: bad_reader)
    group_id = group.id
    with pytest.raises(NonObservationalDashboardRead):
        await reads.DashboardReader(request, actor).read(
            "group_details", {"group_id": str(group.id)}, agency_id=str(agency.id)
        )
    await session.rollback()
    assert (
        await session.scalar(select(ClientGroupModel.name).where(ClientGroupModel.id == group_id))
        == "Synthetic departure"
    )


@asynccontextmanager
async def admitted(*args, **kwargs):
    yield


async def test_streamed_luna_lookup_saved_replay_and_interrupted_retry(workspace, monkeypatch):
    _, actor, agency, _, group, _, store = workspace
    monkeypatch.setattr(chat, "assistant_admission", admitted)
    request = SimpleNamespace(
        is_disconnected=lambda: asyncio.sleep(0, result=False),
        scope={"type": "http", "app": FastAPI()},
    )
    body = ChatRequest(
        request_id=uuid4(), conversation_id=uuid4(), text="Tell me this group's name"
    )
    settings = AssistantSettings(openai_api_key=SecretStr("not-a-real-key"), _env_file=None)

    class Provider:
        calls = 0

        def require_ready(self):
            pass

        async def responses(self, inputs, tools, instructions):
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "completed",
                    "response": {
                        "usage": {},
                        "output": [
                            {
                                "type": "function_call",
                                "name": "call_mcp_tool",
                                "call_id": "fixture-call",
                                "arguments": json.dumps(
                                    {
                                        "tool_name": "group_details",
                                        "arguments_json": json.dumps({"group_id": str(group.id)}),
                                    }
                                ),
                            }
                        ],
                    },
                }
            else:
                assert "Synthetic departure" in json.dumps(inputs)
                assert "protected-upload-token" not in json.dumps(inputs)
                yield {"type": "delta", "text": "Your group is Synthetic departure."}
                yield {
                    "type": "completed",
                    "response": {"output": [], "usage": {"input_tokens": 100, "output_tokens": 9}},
                }

    # The chat loop receives the MCP contract. Real grant and SDK execution are
    # covered in test_assistant_mcp_bridge; retain SQL projection coverage here.
    async def dispatch(bridge, name, arguments):
        assert name == "call_mcp_tool"
        result = await reads.DashboardReader(Request(request.scope), actor).read(
            "group_details", {"group_id": str(group.id)}, agency_id=str(agency.id))
        return {"result": result, "observed_at": result["observed_at"]}
    monkeypatch.setattr(chat.MCPAssistantBridge, "dispatch", dispatch)

    provider = Provider()
    events = [
        event async for event in chat.chat_events(request, actor, body, settings, store, provider)
    ]
    assert [event["type"] for event in events][-1] == "done"
    assert any(
        event["type"] == "source" and event["source"]["view"] == "group_details" for event in events
    )
    replay = [
        event async for event in chat.chat_events(request, actor, body, settings, store, provider)
    ]
    assert [event["type"] for event in replay] == ["replay", "done"]
    assert provider.calls == 2
    with pytest.raises(AssistantError) as conflict:
        changed = body.model_copy(update={"text": "A different prompt with the same request id"})
        _ = [
            event
            async for event in chat.chat_events(request, actor, changed, settings, store, provider)
        ]
    assert conflict.value.code == "request_conflict"
    interrupted = body.model_copy(update={"request_id": uuid4()})
    await store.claim_request(
        interrupted.conversation_id, interrupted.request_id, "claimed-before-crash"
    )
    with pytest.raises(AssistantError) as retry:
        _ = [
            event
            async for event in chat.chat_events(
                request, actor, interrupted, settings, store, provider
            )
        ]
    assert retry.value.code == "request_interrupted"
    assert provider.calls == 2


async def test_unknown_tools_and_sql_are_not_available_to_the_model(workspace, monkeypatch):
    _, actor, _, _, _, _, store = workspace
    monkeypatch.setattr(chat, "assistant_admission", admitted)

    class Provider:
        calls = 0

        def require_ready(self):
            pass

        async def responses(self, inputs, tools, instructions):
            assert {tool["name"] for tool in tools} == {
                "list_mcp_tools",
                "call_mcp_tool",
                "create_images",
            }
            self.calls += 1
            if self.calls == 1:
                yield {
                    "type": "completed",
                    "response": {
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "malicious",
                                "name": "execute_sql",
                                "arguments": '{"sql":"DELETE FROM users"}',
                            }
                        ]
                    },
                }
            else:
                assert "query_rejected" in inputs[-1]["output"]
                yield {"type": "delta", "text": "I can only read dashboard information."}
                yield {"type": "completed", "response": {"output": []}}

    request = SimpleNamespace(is_disconnected=lambda: asyncio.sleep(0, result=False))
    events = [
        event
        async for event in chat.chat_events(
            request,
            actor,
            ChatRequest(request_id=uuid4(), conversation_id=uuid4(), text="Delete all data"),
            AssistantSettings(_env_file=None),
            store,
            Provider(),
        )
    ]
    assert events[-1]["type"] == "done"
