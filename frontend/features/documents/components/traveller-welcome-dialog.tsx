"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import { RefreshCw, Send } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import { DialogFrame, ErrorBanner } from "@/features/whatsapp/components/whatsapp-dialog-ui";
import type { TravellerWelcomePreview } from "@/types/document-distribution.types";
import { eligibleWelcomePhones, MAX_WELCOME_NUMBERS_PER_SEND, selectedWelcomePhones, welcomeStatusLabel, welcomeStatusTone } from "./traveller-welcome-model";

interface TravellerWelcomeDialogProps {
  preview: TravellerWelcomePreview | undefined;
  loading: boolean;
  refreshing: boolean;
  loadError: Error | null;
  sending: boolean;
  sendError: Error | null;
  imagePreviewUrl?: string;
  imageUploading?: boolean;
  imageError?: string | null;
  onReplaceImage?: (file: File) => void;
  onUseOriginalImage?: () => void;
  onSourceChange: (id: string) => void;
  onRefresh: () => void;
  onClose: () => void;
  onSend: (phoneNumbers: string[]) => void;
}

export function TravellerWelcomeDialog({ preview, loading, refreshing, loadError, sending, sendError, imagePreviewUrl, imageUploading = false, imageError, onReplaceImage, onUseOriginalImage, onSourceChange, onRefresh, onClose, onSend }: TravellerWelcomeDialogProps) {
  const [selection, setSelection] = useState<string[] | null>(null);
  const [examplePhone, setExamplePhone] = useState<string | null>(null);
  const eligiblePhones = useMemo(() => eligibleWelcomePhones(preview?.recipients ?? []), [preview?.recipients]);
  const eligibleSet = useMemo(() => new Set(eligiblePhones), [eligiblePhones]);
  const selectedPhones = selectedWelcomePhones(eligiblePhones, selection);
  const selectedSet = new Set(selectedPhones);
  const examples = preview?.recipients.filter((row) => row.phone_number && row.rendered_message) ?? [];
  const example = examples.find((row) => row.phone_number === examplePhone)
    ?? examples.find((row) => row.phone_number && selectedSet.has(row.phone_number))
    ?? examples[0];
  const busy = sending || refreshing || imageUploading;
  const headerImageUrl = imagePreviewUrl ?? preview?.header_image_url;
  const canSend = Boolean(preview?.can_send && preview.preview_token && selectedPhones.length && !busy && !loading && !loadError);

  return (
    <DialogFrame title="Welcome new traveller numbers" description="Review the same welcome used for the linked broadcast. Only numbers still needing a welcome can be selected." widthClass="max-w-5xl" layout="composer" isBusy={sending || imageUploading} onClose={onClose}>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4 sm:px-7">
        {loading ? <p role="status" className="py-8 text-sm text-slate-600">Preparing traveller welcome preview…</p> : loadError ? <ErrorBanner message={loadError.message || "The welcome preview could not be loaded."} /> : preview ? <>
          {preview.sources.length > 1 && <div><label htmlFor="traveller-welcome-source" className="text-sm font-medium text-slate-800">Welcome message from</label><select id="traveller-welcome-source" className="mt-1 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" value={preview.source_broadcast_id ?? ""} disabled={busy} onChange={(event) => onSourceChange(event.target.value)}>{!preview.source_broadcast_id && <option value="" disabled>Choose linked broadcast</option>}{preview.sources.map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></div>}
          {preview.sources.length <= 1 && preview.source_broadcast_name && <p className="text-sm text-slate-600">Welcome message from <span className="font-semibold text-slate-900">{preview.source_broadcast_name}</span></p>}
          <div className="rounded-lg border border-blue-100 bg-blue-50 px-3 py-2 text-sm leading-6 text-blue-900">{preview.summary.already_welcomed} already welcomed · {preview.summary.in_progress} awaiting delivery. These numbers will not receive another welcome. Each shared number receives one welcome.</div>
          {eligiblePhones.length > MAX_WELCOME_NUMBERS_PER_SEND && <p className="text-sm leading-6 text-slate-600">Send up to 1,500 numbers at a time. The first 1,500 are selected; remaining numbers stay ready for your next send.</p>}
          {preview.configuration_error && <ErrorBanner message={preview.configuration_error} />}
          <div className="grid items-start gap-5 lg:grid-cols-2">
            <div className="overflow-hidden rounded-xl border border-slate-200">
              <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-sm font-semibold text-slate-900">Traveller WhatsApp numbers</div>
              <div className="max-h-[420px] divide-y divide-slate-100 overflow-y-auto">
                {preview.recipients.length === 0 && <p className="p-4 text-sm text-slate-500">No submitted traveller numbers yet.</p>}
                {preview.recipients.map((row, index) => {
                  const eligible = Boolean(row.phone_number && eligibleSet.has(row.phone_number));
                  return <div key={row.phone_number ?? (row.passenger_ids.join(":") || String(index))} className="space-y-2 px-4 py-3">
                    <label className="flex items-start gap-3">
                      <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 rounded border-slate-300" checked={Boolean(row.phone_number && selectedSet.has(row.phone_number))} disabled={!eligible || busy || (selectedPhones.length >= MAX_WELCOME_NUMBERS_PER_SEND && !selectedSet.has(row.phone_number ?? ""))} aria-label={`Welcome ${row.phone_number ?? row.passenger_names.join(", ")}`} onChange={() => { const phone = row.phone_number; if (!phone) return; setSelection((current) => { const active = selectedWelcomePhones(eligiblePhones, current); return active.includes(phone) ? active.filter((value) => value !== phone) : [...active, phone]; }); }} />
                      <span className="min-w-0 flex-1"><span className="block break-words text-sm font-semibold text-slate-900">{row.passenger_names.join(", ")}</span><span className="mt-0.5 block text-sm text-slate-600">{row.phone_number || "No valid traveller number"}</span></span>
                    </label>
                    <div className="pl-7"><Badge variant={welcomeStatusTone(row.status)}>{welcomeStatusLabel(row.status)}</Badge>{row.reason && <p className="mt-1 text-xs leading-5 text-slate-600">{row.reason}</p>}</div>
                  </div>;
                })}
              </div>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-4">
              <h3 className="text-sm font-semibold text-emerald-900">Welcome message preview</h3>
              {examples.length > 1 && <><label htmlFor="traveller-welcome-example" className="mt-3 block text-xs font-medium text-slate-700">Preview for traveller</label><select id="traveller-welcome-example" className="mt-1 w-full rounded-lg border border-emerald-200 bg-white px-2 py-2 text-sm" value={example?.phone_number ?? ""} onChange={(event) => setExamplePhone(event.target.value)}>{examples.map((row) => <option key={row.phone_number} value={row.phone_number ?? ""}>{row.passenger_names.join(", ")} · {row.phone_number}</option>)}</select></>}
              {headerImageUrl && <Image src={headerImageUrl} alt="Welcome message header" width={480} height={270} unoptimized className="mt-3 h-auto max-h-52 w-full rounded-lg bg-white object-contain" />}
              {onReplaceImage && <div className="mt-3"><label htmlFor="traveller-welcome-image" className="block text-xs font-medium text-slate-700">Replace welcome image (optional)</label><input id="traveller-welcome-image" type="file" accept="image/jpeg,image/png" disabled={busy || !preview.source_broadcast_id} className="mt-1 block w-full text-xs text-slate-600 file:mr-3 file:rounded-md file:border file:border-slate-200 file:bg-white file:px-2 file:py-2" onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) onReplaceImage(file); }} /><p className="mt-1 text-xs leading-5 text-slate-500">JPG or PNG, up to 5 MB. Use this if the previous welcome image needs replacing.</p>{imageUploading && <p role="status" className="mt-1 text-xs text-blue-700">Uploading welcome image…</p>}{imageError && <p role="alert" className="mt-1 text-xs text-red-700">{imageError}</p>}</div>}
              {onUseOriginalImage && <Button type="button" size="sm" variant="outline" className="mt-2" disabled={busy} onClick={onUseOriginalImage}>Use original image</Button>}
              {example?.rendered_message ? <p className="mt-3 whitespace-pre-wrap break-words rounded-lg border border-emerald-100 bg-white p-4 text-sm leading-6 text-slate-800">{example.rendered_message}</p> : <p className="mt-3 text-sm leading-6 text-slate-600">A welcome preview will appear when a valid traveller number and welcome message are available.</p>}
              <p className="mt-3 text-xs leading-5 text-slate-600">Documents stay blocked until welcome delivery is confirmed. Sending this welcome does not send tickets, visas, or a passport-link message.</p>
            </div>
          </div>
        </> : null}
        {sendError && <ErrorBanner message={sendError.message} />}
      </div>
      <div className="shrink-0 border-t border-slate-200 px-5 py-4 sm:px-7">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <Button type="button" variant="outline" onClick={onRefresh} disabled={busy}><RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />{refreshing ? "Refreshing status" : "Refresh status"}</Button>
          <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="secondary" disabled={sending || imageUploading} onClick={onClose}>Close</Button><Button type="button" disabled={!canSend} isLoading={sending} onClick={() => { if (canSend) onSend(selectedPhones); }}><Send className="h-4 w-4" />Send welcome to {selectedPhones.length} {selectedPhones.length === 1 ? "number" : "numbers"}</Button></div>
        </div>
      </div>
    </DialogFrame>
  );
}
