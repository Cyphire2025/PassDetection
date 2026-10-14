"use client";
import dynamic from "next/dynamic";
import { Camera, CheckCircle2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PASSPORT_UPLOAD_PAGES } from "@/features/passports/types/upload-configuration";
import type { DraftSide } from "@/features/travellers/api/returning-draft.api";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { configuredPassportPages, type getUploadFlowSettings } from "../services/configured-upload";
import { PUBLIC_UPLOAD_ACCEPT } from "../services/public-upload-file";
import { draftSideDisabled, useDraftDocumentUpload } from "../hooks/use-draft-document-upload";
import { FreshDocumentPreview } from "./fresh-document-preview";

const SmartCamera = dynamic(() => import("./smart-camera").then((module) => module.SmartCamera), { ssr: false });
const VisaCamera = dynamic(() => import("./visa-selfie-camera").then((module) => module.VisaSelfieCamera), { ssr: false });
const documentLabel = (side: DraftSide) => side === "photo" ? "Traveller photo" : PASSPORT_UPLOAD_PAGES.find((page) => page.id === side)!.label;
export function FreshDocuments({ state, settings, token, sessionId, previews = true, frontFirst = false }: { state: DraftDocumentInputs; settings: ReturnType<typeof getUploadFlowSettings>; token: string; sessionId: string; previews?: boolean; frontFirst?: boolean }) {
  const { camera, setCamera, error, preparing, upload } = useDraftDocumentUpload(state, token, sessionId);
  const { uploadConfig: config } = settings;
  const pages: DraftSide[] = settings.passportEnabled ? configuredPassportPages(config, state.payload?.collection?.acquisition_mode ?? "file", settings.allowFilesFromDevice) : [];
  const sides = [...pages, ...(settings.selfieEnabled ? ["photo" as const] : [])];
  const busy = state.pending || preparing;
  return <section aria-label="Your documents" className="space-y-4">
    {sides.map((side) => {
      const document = state.draft?.documents.find((item) => item.side === side);
      const label = documentLabel(side);
      const canCamera = side === "photo" ? config.visa_photo_live_capture : config.passport_live_scan && (side === "front" || side === "back");
      const canFile = side === "photo" ? config.visa_photo_upload : settings.allowFilesFromDevice;
      const disabled = draftSideDisabled(state, side, frontFirst, busy);
      return <div key={side} className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">{document && <CheckCircle2 className="h-4 w-4 text-emerald-600" />}{label}</h3>
        <div className="mt-3 flex flex-wrap gap-2">
          {canFile && <label className={`relative inline-flex min-h-11 items-center gap-2 rounded-xl border border-blue-200 px-4 py-2 text-sm font-medium text-blue-700 ${disabled ? "opacity-50" : "hover:bg-blue-50"}`}><Upload className="h-4 w-4" />{document ? "Replace image" : "Choose file"}<input type="file" className="absolute inset-0 w-full cursor-pointer opacity-0 focus-visible:opacity-100" aria-label={`Upload ${label.toLowerCase()}`} accept={PUBLIC_UPLOAD_ACCEPT} disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void upload(side, file, "file"); }} /></label>}
          {canCamera && <Button type="button" variant="secondary" disabled={disabled} onClick={() => setCamera(side as "front" | "back" | "photo")}><Camera className="mr-2 h-4 w-4" />Use camera</Button>}
        </div>
        {!document && <p className="mt-3 text-xs leading-5 text-slate-500">{side === "photo" ? "A clear, recent photo with a plain background." : "Include the whole page, with clear text and no glare. Files up to 2 MB."}</p>}
        {previews && document && <FreshDocumentPreview key={document.id} id={document.id} label={label} api={state.api} />}
      </div>;
    })}
    {preparing && <p role="status" className="text-sm text-blue-700">Preparing your image…</p>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {camera === "photo" ? <VisaCamera onCapture={(file) => { void upload("photo", file, "camera"); }} onCancel={() => setCamera(undefined)} /> : camera && <SmartCamera pageSide={camera} allowFileFallback={settings.allowFilesFromDevice} onCapture={(file) => { void upload(camera, file, "camera"); }} onCancel={() => setCamera(undefined)} />}
  </section>;
}
