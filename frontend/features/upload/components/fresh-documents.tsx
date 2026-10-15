"use client";
import dynamic from "next/dynamic";
import { PASSPORT_UPLOAD_PAGES } from "@/features/passports/types/upload-configuration";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { ReturningDocument } from "@/features/travellers/types";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { configuredPassportPages, type getUploadFlowSettings } from "../services/configured-upload";
import { DOCUMENT_PREVIEW_ORDER, documentSide } from "../services/document-preview-order";
import { useDraftDocumentUpload } from "../hooks/use-draft-document-upload";
import { DraftDocumentCard } from "./draft-document-card";

const SmartCamera = dynamic(() => import("./smart-camera").then((module) => module.SmartCamera), { ssr: false });
const VisaCamera = dynamic(() => import("./visa-selfie-camera").then((module) => module.VisaSelfieCamera), { ssr: false });
const documentLabel = (side: DraftSide) => side === "photo" ? "Traveller photo" : PASSPORT_UPLOAD_PAGES.find((page) => page.id === side)!.label;
type Props = { state: DraftDocumentInputs; settings: ReturnType<typeof getUploadFlowSettings>; token: string; sessionId: string; savedDocuments?: ReturningDocument[]; editableSides?: readonly DraftSide[]; onUploadBusyChange?: (busy: boolean) => void };
export function FreshDocuments({ state, settings, token, sessionId, savedDocuments = [], editableSides, onUploadBusyChange }: Props) {
  const { camera, setCamera, error, preparing, pendingSide, selected, upload } = useDraftDocumentUpload(state, token, sessionId);
  const startUpload = (side: DraftSide, file: File, source: "file" | "camera") => {
    onUploadBusyChange?.(true);
    void upload(side, file, source).finally(() => onUploadBusyChange?.(false));
  };
  const { uploadConfig: config } = settings;
  const pages: DraftSide[] = settings.passportEnabled ? configuredPassportPages(config, state.payload?.collection?.acquisition_mode ?? "file", settings.allowFilesFromDevice) : [];
  const enabled: DraftSide[] = [...pages, ...(settings.selfieEnabled ? ["photo" as const] : [])];
  const savedFor = (side: DraftSide) => savedDocuments.find((image) => documentSide(image.label) === side);
  const sides = DOCUMENT_PREVIEW_ORDER.filter((side) => enabled.includes(side) || (side !== "cover" && side !== "back_cover" && savedFor(side)));
  return <section aria-label="Your documents" className="space-y-4">
    {sides.map((side) => {
      const editable = enabled.includes(side) && (!editableSides || editableSides.includes(side));
      const canCamera = editable && (side === "photo" ? config.visa_photo_live_capture : config.passport_live_scan && (side === "front" || side === "back"));
      const canFile = editable && (side === "photo" ? config.visa_photo_upload : settings.allowFilesFromDevice);
      const status = documentProcessingStatus(side, state, pendingSide, config.passport_ecr_enabled);
      return <DraftDocumentCard key={side} side={side} label={documentLabel(side)} state={state} selected={selected[side]} saved={savedFor(side)} status={status} canFile={canFile} canCamera={canCamera} disabled={state.pending || preparing} onUpload={(file) => startUpload(side, file, "file")} onCamera={() => setCamera(side as "front" | "back" | "photo")} />;
    })}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {camera === "photo" ? <VisaCamera onCapture={(file) => startUpload("photo", file, "camera")} onCancel={() => setCamera(undefined)} /> : camera && <SmartCamera pageSide={camera} allowFileFallback={settings.allowFilesFromDevice} onCapture={(file) => startUpload(camera, file, "camera")} onCancel={() => setCamera(undefined)} />}
  </section>;
}
function documentProcessingStatus(side: DraftSide, state: DraftDocumentInputs, pendingSide: DraftSide | undefined, ecr: boolean) {
  const uploading = pendingSide === side || state.draft?.documents.some((document) => document.side === side && document.state === "uploading");
  if (side === "front" && (uploading || ["pending", "running"].includes(state.draft?.extraction_status ?? ""))) return "Extracting details…";
  if (side === "back" && ecr && (uploading || ["pending", "running"].includes(state.draft?.ecr_status ?? ""))) return "Verifying ECR presence…";
  if (uploading) return "Uploading document…";
}
