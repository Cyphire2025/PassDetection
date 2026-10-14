"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { returningDraftApi, type DraftPayload, type DraftSide, type ReturningDraft } from "../api/returning-draft.api";
import { clearDraftResume, saveDraftResume } from "../services/draft-resume";
import { freshPayload as payloadOf, reconcileFresh } from "@/features/upload/services/fresh-draft-state";
import type { FreshCollection, FreshPayload } from "@/features/upload/api/fresh-draft.api";
import { useDraftAutosave } from "./use-draft-autosave";
import { useDraftPolling } from "./use-draft-polling";
import { prepareDraftUpload, sendDraftUpload, type DraftUploadOperation } from "../services/draft-upload-operation";
import { draftChecksPending } from "../services/draft-check-state";
import { useDraftImageLifecycle } from "./use-draft-image-lifecycle";
import { useDraftInitialization } from "./use-draft-initialization";
import type { ReturningHistory, ReturningOwnedSource } from "../types";

const messageOf = (cause: unknown) => cause && typeof cause === "object" && "message" in cause && typeof cause.message === "string" ? cause.message : "Your draft could not be saved. Keep this page open and retry.";

/** Serial revisions prevent autosave, upload, OTP and final-submit races. */
export function useReturningDraft(history: ReturningHistory, token: string, ownedSource?: ReturningOwnedSource) {
  const [draft, setDraft] = useState<ReturningDraft>();
  const [payload, setPayload] = useState<FreshPayload>();
  const [pending, setPending] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string>();
  const current = useRef<ReturningDraft | undefined>(undefined);
  const values = useRef<FreshPayload | undefined>(undefined);
  const version = useRef(0);
  const savedVersion = useRef(0);
  const saveRequest = useRef<{ payload: FreshPayload; base: FreshPayload; revision: number; key: string; version: number } | null>(null);
  const uploadRequest = useRef<DraftUploadOperation | null>(null);
  const controller = useRef<AbortController | null>(null);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const submitKey = useRef(crypto.randomUUID());
  const adopt = useCallback((view: ReturningDraft, base?: FreshPayload) => {
    if (current.current?.id === view.id && current.current.revision > view.revision) return;
    const merged = base && values.current ? reconcileFresh(base, values.current, payloadOf(view), true) : payloadOf(view);
    current.current = view; setDraft(view);
    values.current = merged; setPayload(merged);
  }, []);
  const load = useCallback((signal: AbortSignal) => returningDraftApi.start(history.review_version, signal), [history.review_version]);
  const opened = useCallback((view: ReturningDraft) => {
    version.current = 0; savedVersion.current = 0; saveRequest.current = null; uploadRequest.current = null; queue.current = Promise.resolve(); setDirty(false); adopt(view);
    if (view.status === "submitted") clearDraftResume(token); else submitKey.current = saveDraftResume(token, view.expires_at, "returning").submissionKey;
  }, [adopt, token]);
  useDraftInitialization(load, opened, controller, setPending, setError, messageOf, `${token}:${history.review_version}:${attempt}`);

  const serialized = useCallback(<T,>(operation: (signal: AbortSignal) => Promise<T>, foreground = false): Promise<T> => {
    const signal = controller.current?.signal;
    const result = queue.current.catch(() => undefined).then(async () => {
      if (!signal || signal.aborted) throw new DOMException("Aborted", "AbortError");
      if (foreground) setPending(true);
      setError(undefined);
      try { return await operation(signal); }
      catch (cause) { if (!signal.aborted) setError(messageOf(cause)); throw cause; }
      finally { if (foreground && !signal.aborted) setPending(false); }
    });
    queue.current = result;
    return result;
  }, []);
  const save = useCallback(async (signal: AbortSignal) => {
    if (!current.current || !values.current) throw new Error("The secure draft is still loading.");
    if (savedVersion.current === version.current) return;
    const request = saveRequest.current ?? { payload: values.current, base: payloadOf(current.current), revision: current.current.revision, key: crypto.randomUUID(), version: version.current };
    saveRequest.current = request;
    let result: ReturningDraft;
    try { result = await returningDraftApi.save(request.payload, request.revision, request.key, current.current.id, signal); }
    catch (cause) {
      if (!cause || typeof cause !== "object" || !("status" in cause) || cause.status !== 409) throw cause;
      const remote = await returningDraftApi.read(current.current.id, signal);
      if (remote.id !== current.current.id || remote.status !== "active") throw cause;
      const merged = reconcileFresh(request.base, request.payload, payloadOf(remote));
      const retry = { payload: merged, base: payloadOf(remote), revision: remote.revision, key: crypto.randomUUID(), version: request.version };
      saveRequest.current = retry;
      result = await returningDraftApi.save(retry.payload, retry.revision, retry.key, current.current.id, signal);
    }
    if (signal.aborted) return;
    adopt(result, request.payload); savedVersion.current = request.version; saveRequest.current = null;
    setDirty(savedVersion.current !== version.current);
  }, [adopt]);
  const flush = useCallback(() => serialized(save), [serialized, save]);
  const update = useCallback((section: keyof DraftPayload, key: string, value: string) => {
    if (!values.current) return;
    values.current = { ...values.current, [section]: { ...values.current[section], [key]: value } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  const collection = useCallback((patch: Partial<FreshCollection>) => {
    if (!values.current) return;
    if (Object.entries(patch).every(([key, value]) => values.current?.collection?.[key as keyof FreshCollection] === value)) return;
    values.current = { ...values.current, collection: { acquisition_mode: "file", submission_mode: "single", ...values.current.collection, ...patch } };
    version.current++; setPayload(values.current); setDirty(true);
  }, []);
  useDraftAutosave(dirty, payload, flush);
  const images = useMemo(() => ({ activity: (signal?: AbortSignal) => returningDraftApi.activity(current.current!.id, signal), discard: (revision: number, signal?: AbortSignal, keepalive = false) => returningDraftApi.discard(revision, current.current!.id, signal, keepalive) }), []);
  const cancel = useCallback(() => controller.current?.abort(), []);
  const resume = useCallback(() => { setPending(true); setAttempt((value) => value + 1); }, []);
  const refresh = useCallback(() => serialized(async (signal) => {
    await save(signal); const base = values.current; const view = await returningDraftApi.read(current.current!.id, signal);
    if (!signal.aborted) adopt(view, base);
  }), [serialized, save, adopt]);
  const discard = useDraftImageLifecycle(current, draft, images, cancel, resume, token, refresh);
  useDraftPolling(draftChecksPending(draft), refresh, setError, draft?.documents.map((item) => item.id).join(","));
  const upload = useCallback((side: DraftSide, file: File) => serialized(async (signal) => {
    await save(signal);
    const request = await prepareDraftUpload(uploadRequest.current, side, file, current.current!);
    signal.throwIfAborted(); const base = values.current;
    uploadRequest.current = request;
    const result = await sendDraftUpload(request, (operation) => returningDraftApi.upload(side, file, operation.revision, operation.key, operation.draftId, signal, operation.assetId),
      () => returningDraftApi.read(request.draftId, signal), (operation) => { uploadRequest.current = operation; }, (view) => adopt(view, base), signal);
    if (!signal.aborted) { uploadRequest.current = null; adopt(result, base); return { documents: result.documents }; }
  }, true), [serialized, save, adopt]);
  const complete = useCallback(() => serialized(async (signal) => {
    await save(signal);
    if (savedVersion.current !== version.current) throw new Error("Your latest edit is still saving. Please retry submission.");
    const result = await returningDraftApi.complete({ expected_revision: current.current!.revision,
      review_version: history.review_version, question_version: history.question_version,
      ...(history.participation_revision != null ? { expected_participation_revision: history.participation_revision } : {}),
      ...(ownedSource ? { owned_source: { source_submission_id: ownedSource.source_submission_id, expected_extraction_revision: ownedSource.expected_extraction_revision } } : {}),
      information_confirmed: true, idempotency_key: submitKey.current }, current.current!.id, signal, ownedSource?.uploadSessionId);
    if (ownedSource && !result.source_submission_id) throw new Error("Your saved details could not be linked to this upload. Please retry submission.");
    if (!signal.aborted) { adopt({ ...current.current!, status: "submitted" }); clearDraftResume(token); }
    return result;
  }, true), [serialized, save, history, token, ownedSource, adopt]);
  const leave = () => serialized(async (signal) => {
    await save(signal);
    if (savedVersion.current !== version.current) throw new Error("Your latest edit is saving. Please try again.");
    const base = values.current, view = await discard(signal);
    if (view && !signal.aborted) { adopt(view, base); uploadRequest.current = null; }
  }, true);
  const retry = () => {
    if (current.current) { void refresh().catch(() => undefined); return; }
    setPending(true); setError(undefined); setAttempt((value) => value + 1);
  };
  return { draft, payload, pending, dirty, error, update, collection, flush, refresh, retry, upload, complete, leave, serialized };
}
