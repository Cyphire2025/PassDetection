"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { assistantApi, assistantMessage } from "../api";
import type { Asset, AssistantStatus, Message, StreamEvent, Turn } from "../types";

function turnMessages(turn: Turn): Message[] {
  return [{ id: `${turn.id}-user`, role: "user", text: turn.user, attachments: turn.attachments },
    { id: turn.id, role: "assistant", text: turn.assistant, images: turn.images, sources: turn.sources }];
}

export function useAssistant(onAnswer: (text: string) => void, onImage: (image: Asset) => void) {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [access, setAccess] = useState<"loading" | "guest" | "denied" | "ready" | "offline">("loading");
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [observedAt, setObservedAt] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const historySequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const account = useRef<string | null>(null);
  const callbacks = useRef({ onAnswer, onImage });
  useEffect(() => { callbacks.current = { onAnswer, onImage }; }, [onAnswer, onImage]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await assistantApi.status(signal, Boolean(account.current));
      if (account.current && value.account_id && account.current !== value.account_id) {
        controller.current?.abort(); setMessages([]); setConversationId(null); setOlderCursor(null); historySequence.current++;
      }
      account.current = value.account_id || null;
      setStatus(value); setAccess("ready");
      const live = await assistantApi.live(signal);
      setObservedAt(live.observed_at);
    } catch (cause) {
      if (signal?.aborted) return;
      const httpStatus = (cause as { status?: number; response?: { status: number } }).status ?? (cause as { response?: { status: number } }).response?.status;
      const code = (cause as { code?: string }).code;
      if (httpStatus === 401 || httpStatus === 403 || code === "AUTH_SESSION_EXPIRED") {
        controller.current?.abort(); setMessages([]); setConversationId(null); setOlderCursor(null); setStatus(null); account.current = null; historySequence.current++;
      }
      setAccess(httpStatus === 401 || code === "AUTH_SESSION_EXPIRED" ? "guest" : httpStatus === 403 ? "denied" : "offline");
      setObservedAt(null);
    }
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    void refresh(abort.signal);
    const timer = setInterval(() => { if (!document.hidden) void refresh(abort.signal); }, 30000);
    const visible = () => { if (!document.hidden) void refresh(abort.signal); };
    document.addEventListener("visibilitychange", visible);
    return () => { abort.abort(); controller.current?.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [refresh]);

  const stop = useCallback(() => { controller.current?.abort(); }, []);
  const send = useCallback(async (text: string, attachments: Asset[] = [], mode: "chat" | "image" = "chat", imageCount = 1) => {
    if (controller.current || !status?.configured || !text.trim()) return false;
    const abort = new AbortController(); controller.current = abort;
    const id = crypto.randomUUID();
    const conversation = conversationId || crypto.randomUUID();
    setConversationId(conversation); setBusy(true); setError(""); setProgress(mode === "image" ? "Creating your images" : "Thinking through your request");
    setMessages((current) => [...current, { id: `${id}-user`, role: "user", text, attachments },
      { id, role: "assistant", text: "", images: [], sources: [], streaming: true }]);
    let answer = "";
    let completed = false;
    let failed = false;
    const update = (change: (message: Message) => Message) => setMessages((current) => current.map((message) => message.id === id ? change(message) : message));
    const receive = (event: StreamEvent) => {
      if (event.type === "status") setProgress(event.message);
      else if (event.type === "text_delta") { answer += event.text; update((message) => ({ ...message, text: message.text + event.text })); }
      else if (event.type === "source") update((message) => ({ ...message, sources: [...message.sources || [], event.source] }));
      else if (event.type === "image") { update((message) => ({ ...message, images: [...message.images || [], event.image] })); callbacks.current.onImage(event.image); }
      else if (event.type === "replay") { answer = event.turn.assistant; update((message) => ({ ...message, text: answer, images: event.turn.images, sources: event.turn.sources })); }
      else if (event.type === "error") { failed = true; update((message) => ({ ...message, error: event.message })); }
      else if (event.type === "done") completed = true;
    };
    try {
      await assistantApi.stream({ request_id: id, conversation_id: conversation, text,
        attachment_ids: attachments.map((file) => file.id), mode, image_count: imageCount }, abort.signal, receive);
      if (completed && !failed && answer) callbacks.current.onAnswer(answer);
    } catch (cause) {
      update((message) => ({ ...message, error: abort.signal.aborted ? "Response stopped. Reopen this conversation to check whether an answer finished saving." : assistantMessage(cause, "The assistant could not complete this request.") }));
    } finally {
      controller.current = null; setBusy(false); setProgress("");
      update((message) => ({ ...message, streaming: false }));
    }
    return true;
  }, [conversationId, status?.configured]);

  const newConversation = useCallback(() => { stop(); historySequence.current++; setConversationId(null); setOlderCursor(null); setMessages([]); setError(""); }, [stop]);
  const openConversation = useCallback(async (id: string) => {
    if (controller.current) return;
    const sequence = ++historySequence.current;
    try {
      const page = await assistantApi.conversation(id);
      if (sequence !== historySequence.current) return;
      setMessages(page.items.sort((a, b) => a.created_at.localeCompare(b.created_at)).flatMap(turnMessages));
      setOlderCursor(page.next_cursor);
      setConversationId(id); setError("");
    } catch { setError("This conversation could not be opened. Please try again."); }
  }, []);
  const loadEarlier = useCallback(async () => {
    if (!conversationId || !olderCursor || loadingHistory || controller.current) return;
    const sequence = historySequence.current;
    setLoadingHistory(true);
    try {
      const page = await assistantApi.conversation(conversationId, olderCursor);
      if (sequence !== historySequence.current) return;
      const earlier = page.items.sort((a, b) => a.created_at.localeCompare(b.created_at)).flatMap(turnMessages);
      setMessages((current) => [...earlier.filter((item) => !current.some((message) => message.id === item.id)), ...current]);
      setOlderCursor(page.next_cursor);
    } catch { setError("Earlier messages could not be loaded. Please try again."); }
    finally { setLoadingHistory(false); }
  }, [conversationId, olderCursor, loadingHistory]);

  return { status, access, messages, busy, progress, error, setError, observedAt, conversationId,
    send, stop, refresh, newConversation, openConversation, olderCursor, loadingHistory, loadEarlier };
}
