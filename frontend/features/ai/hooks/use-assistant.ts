"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { assistantApi, assistantMessage } from "../api";
import { rememberedConversation, rememberConversation } from "../last-conversation";
import type { Asset, AssistantStatus, McpAccessStatus, Message, NativeEvent, StreamEvent, Turn } from "../types";

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
  const [mcpAccess, setMcpAccess] = useState<McpAccessStatus | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const historySequence = useRef(0);
  const refreshSequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const account = useRef<string | null>(null);
  const restoredAccount = useRef<string | null>(null);
  const callbacks = useRef({ onAnswer, onImage });
  useEffect(() => { callbacks.current = { onAnswer, onImage }; }, [onAnswer, onImage]);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const refreshId = ++refreshSequence.current;
    try {
      const value = await assistantApi.status(signal, Boolean(account.current));
      if (signal?.aborted || refreshId !== refreshSequence.current) return;
      const accountKey = value.account_id ? `${value.account_id}:${value.account_scope || "default"}` : null;
      if (account.current && accountKey && account.current !== accountKey) {
        controller.current?.abort(); setMessages([]); setConversationId(null); setOlderCursor(null); historySequence.current++;
        setMcpAccess(null); setObservedAt(null);
      }
      account.current = accountKey;
      setStatus(value); setAccess("ready");
      if (accountKey && restoredAccount.current !== accountKey) {
        const remembered = rememberedConversation(accountKey);
        if (!remembered) restoredAccount.current = accountKey;
        if (remembered) {
          const sequence = ++historySequence.current;
          try {
            const page = await assistantApi.conversation(remembered);
            if (!signal?.aborted && sequence === historySequence.current && account.current === accountKey) {
              setMessages(page.items.sort((a, b) => a.created_at.localeCompare(b.created_at)).flatMap(turnMessages));
              setConversationId(remembered); setOlderCursor(page.next_cursor);
              restoredAccount.current = accountKey;
            }
          } catch (cause) {
            if (!signal?.aborted && sequence === historySequence.current && account.current === accountKey) {
              restoredAccount.current = accountKey;
              const status = (cause as { status?: number }).status;
              if (status === 404 || status === 410 || status === 403) rememberConversation(accountKey, null);
              else if (!signal?.aborted) setError("Your last chat could not be restored. Open Conversations to try again.");
            }
          }
        }
      }
      if (signal?.aborted || refreshId !== refreshSequence.current || account.current !== accountKey) return;
      const live = await assistantApi.live(signal).catch((cause: unknown) => {
        const failure = cause as { status?: number; response?: { status?: number }; code?: string };
        const httpStatus = failure?.status ?? failure?.response?.status;
        if (httpStatus === 401 || httpStatus === 403 || failure?.code === "AUTH_SESSION_EXPIRED") throw cause;
        return null;
      });
      if (signal?.aborted || refreshId !== refreshSequence.current || account.current !== accountKey) return;
      setObservedAt(live?.observed_at ?? null);
      setMcpAccess(live?.mcp ?? { connected: false, code: "mcp_status_unavailable", message: "Workspace access could not be checked. Try again." });
    } catch (cause) {
      if (signal?.aborted || refreshId !== refreshSequence.current) return;
      const httpStatus = (cause as { status?: number; response?: { status: number } }).status ?? (cause as { response?: { status: number } }).response?.status;
      const code = (cause as { code?: string }).code;
      if (httpStatus === 401 || httpStatus === 403 || code === "AUTH_SESSION_EXPIRED") {
        controller.current?.abort(); setMessages([]); setConversationId(null); setOlderCursor(null); setStatus(null); account.current = null; restoredAccount.current = null; historySequence.current++;
      }
      setAccess(httpStatus === 401 || code === "AUTH_SESSION_EXPIRED" ? "guest" : httpStatus === 403 ? "denied" : "offline");
      setObservedAt(null);
      setMcpAccess(null);
    }
  }, []);

  const cancelRefresh = useCallback(() => { refreshSequence.current++; }, []);
  useEffect(() => {
    const abort = new AbortController();
    void Promise.resolve().then(() => { if (!abort.signal.aborted) return refresh(abort.signal); });
    const timer = setInterval(() => { if (!document.hidden) void refresh(abort.signal); }, 30000);
    const visible = () => { if (!document.hidden) void refresh(abort.signal); };
    document.addEventListener("visibilitychange", visible);
    return () => { abort.abort(); cancelRefresh(); controller.current?.abort(); clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [refresh, cancelRefresh]);

  const stop = useCallback(() => { controller.current?.abort(); }, []);
  const beginNative = useCallback(() => {
    if (controller.current) return null;
    const id = conversationId || crypto.randomUUID();
    historySequence.current++; restoredAccount.current = account.current; rememberConversation(account.current, id);
    setConversationId(id); setError(""); return id;
  }, [conversationId]);
  const finishNative = useCallback(() => {
    setMessages((current) => current.map((message) => message.streaming
      ? { ...message, streaming: false, error: "Voice session ended before this reply finished. Reopen the conversation to check saved replies." }
      : message));
  }, []);
  const receiveNative = useCallback((event: NativeEvent) => {
    if (!("turn_id" in event)) return;
    const id = event.turn_id;
    if (event.type === "turn_complete") {
      setMessages((current) => [...current.filter((item) => item.id !== id && item.id !== `${id}-user`), ...turnMessages(event.turn)]);
      return;
    }
    if (event.type === "image") callbacks.current.onImage(event.image);
    setMessages((current) => {
      let next = current;
      if (!next.some((item) => item.id === id)) next = [...next,
        { id: `${id}-user`, role: "user", text: "" }, { id, role: "assistant", text: "", streaming: true }];
      return next.map((message) => {
        if (event.type === "input_transcript" && message.id === `${id}-user`) return { ...message, text: message.text + event.text };
        if (message.id !== id) return message;
        if (event.type === "text_delta") return { ...message, text: message.text + event.text };
        if (event.type === "answer_reset") return { ...message, text: "", error: undefined, streaming: true };
        if (event.type === "source") return { ...message, sources: [...message.sources || [], event.source] };
        if (event.type === "image") return { ...message, images: [...message.images || [], event.image] };
        if (event.type === "interrupted") return { ...message, streaming: false };
        return message;
      });
    });
  }, []);
  const send = useCallback(async (text: string, attachments: Asset[] = [], mode: "chat" | "image" = "chat", imageCount = 1) => {
    if (controller.current || !status?.configured || !text.trim()) return false;
    const abort = new AbortController(); controller.current = abort;
    const id = crypto.randomUUID();
    const conversation = conversationId || crypto.randomUUID();
    historySequence.current++; restoredAccount.current = account.current; rememberConversation(account.current, conversation);
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
      else if (event.type === "error") { failed = true; setError(event.message); update((message) => ({ ...message, error: event.message })); }
      else if (event.type === "done") completed = true;
    };
    try {
      await assistantApi.stream({ request_id: id, conversation_id: conversation, text,
        attachment_ids: attachments.map((file) => file.id), mode, image_count: imageCount }, abort.signal, receive);
      if (completed && !failed && answer) callbacks.current.onAnswer(answer);
    } catch (cause) {
      const failure = abort.signal.aborted ? "Response stopped. Reopen this conversation to check whether an answer finished saving." : assistantMessage(cause, "The assistant could not complete this request.");
      if (!abort.signal.aborted) setError(failure);
      update((message) => ({ ...message, error: failure }));
    } finally {
      controller.current = null; setBusy(false); setProgress("");
      update((message) => ({ ...message, streaming: false }));
    }
    return true;
  }, [conversationId, status?.configured]);

  const newConversation = useCallback(() => { stop(); historySequence.current++; restoredAccount.current = account.current; rememberConversation(account.current, null); setConversationId(null); setOlderCursor(null); setMessages([]); setError(""); }, [stop]);
  const deleteConversation = useCallback(async (id: string) => {
    const owner = account.current;
    const sequence = ++historySequence.current;
    await assistantApi.deleteConversation(id);
    // A late delete response cannot clear a newly opened chat or another account.
    const clear = owner === account.current && sequence === historySequence.current && id === conversationId;
    if (clear) newConversation();
    return clear;
  }, [conversationId, newConversation]);
  const openConversation = useCallback(async (id: string) => {
    if (controller.current) return;
    restoredAccount.current = account.current;
    const sequence = ++historySequence.current;
    try {
      const page = await assistantApi.conversation(id);
      if (sequence !== historySequence.current) return;
      setMessages(page.items.sort((a, b) => a.created_at.localeCompare(b.created_at)).flatMap(turnMessages));
      setOlderCursor(page.next_cursor);
      setConversationId(id); setError("");
      rememberConversation(account.current, id);
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

  return { status, access, messages, busy, progress, error, setError, observedAt, mcpAccess, conversationId,
    send, stop, refresh, newConversation, deleteConversation, openConversation, olderCursor, loadingHistory, loadEarlier, beginNative, receiveNative, finishNative };
}
