"use client";
import { useEffect, useRef, useState } from "react";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { preparePublicUploadFile } from "../services/public-upload-file";
import { freshError } from "../services/fresh-draft-state";

export function useDraftDocumentUpload(state: DraftDocumentInputs, token: string, sessionId: string) {
  const [camera, setCamera] = useState<"front" | "back" | "photo">(), [error, setError] = useState<string>();
  const [preparing, setPreparing] = useState(false);
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const upload = async (side: DraftSide, file: File, source: "file" | "camera") => {
    operation.current?.abort(); const controller = new AbortController(); operation.current = controller;
    setPreparing(true); setError(undefined); setCamera(undefined);
    try {
      const ready = source === "file" ? await preparePublicUploadFile(file, { token, uploadSessionId: sessionId, purpose: side === "photo" ? "visa" : "passport", signal: controller.signal }) : file;
      if (controller.signal.aborted) return;
      state.collection(side === "photo" ? { visa_photo_source: source } : { acquisition_mode: source });
      await state.upload(side, ready);
    } catch (cause) { if (!controller.signal.aborted) setError(freshError(cause)); } finally { if (!controller.signal.aborted) setPreparing(false); }
  };
  return { camera, setCamera, error, preparing, upload };
}

export function draftSideDisabled(state: DraftDocumentInputs, side: DraftSide, frontFirst: boolean, busy: boolean) {
  return busy || (frontFirst && side === "back" && !state.draft?.documents.some((item) => item.side === "front"));
}
