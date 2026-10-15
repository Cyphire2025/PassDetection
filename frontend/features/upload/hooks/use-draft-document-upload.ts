"use client";
import { useState } from "react";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { useSelectedDocumentUploads } from "./use-selected-document-uploads";

export function useDraftDocumentUpload(state: DraftDocumentInputs, token: string, sessionId: string) {
  const [camera, setCamera] = useState<"front" | "back" | "photo">();
  const selection = useSelectedDocumentUploads(state, token, sessionId);
  const upload = async (side: DraftSide, file: File, source: "file" | "camera") => {
    setCamera(undefined);
    await selection.upload(side, file, source);
  };
  return { ...selection, camera, setCamera, preparing: Boolean(selection.pendingSide), upload };
}
