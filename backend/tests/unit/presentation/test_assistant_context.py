"""Bound context without another model call or modifying retained messages."""

from app.presentation.assistant.conversation_context import MAX_CONTEXT_CHARS, recent_context


def test_newest_complete_exchanges_fit_budget_and_preserve_voice_and_attachments():
    history = [{"created_at":f"2026-10-19T00:{index:02}:00Z","user":"u" * 8000,
        "assistant":"a" * 16000,"voice":bool(index % 2),"attachment_ids":[str(index)]} for index in range(12)]
    original = str(history)
    selected = recent_context(history)
    assert len(selected) == 2 and selected[-1]["voice"] is True and selected[-1]["attachment_ids"] == ["11"]
    assert sum(len(item["user"]) + len(item["assistant"]) for item in selected) <= MAX_CONTEXT_CHARS
    assert str(history) == original


def test_short_messages_keep_the_ten_newest_in_order_including_unicode():
    history = [{"created_at":f"2026-10-19T00:{index:02}:00Z","user":"नमस्ते","assistant":str(index)} for index in range(15)]
    selected = recent_context(list(reversed(history)))
    assert [item["assistant"] for item in selected] == [str(index) for index in range(5,15)]
