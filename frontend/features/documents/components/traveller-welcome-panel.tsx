"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { MessageCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui";
import { useSendTravellerWelcome, useTravellerWelcomePreview } from "../hooks/use-traveller-welcome";
import { useTravellerWelcomeImage } from "../hooks/use-traveller-welcome-image";

const TravellerWelcomeDialog = dynamic(
  () => import("./traveller-welcome-dialog").then((module) => module.TravellerWelcomeDialog),
);

export function TravellerWelcomePanel({ groupId, disabled = false, open, onOpenChange }: { groupId: string; disabled?: boolean; open: boolean; onOpenChange: (value: boolean) => void }) {
  const [sourceBroadcastId, setSourceBroadcastId] = useState<string>();
  const [feedback, setFeedback] = useState<string | null>(null);
  const welcomeImage = useTravellerWelcomeImage();
  const preview = useTravellerWelcomePreview(groupId, sourceBroadcastId, welcomeImage.image?.mediaId);
  const send = useSendTravellerWelcome(groupId);
  const summary = preview.data?.summary;
  const refreshPreview = preview.refetch;
  useEffect(() => { if (open) void refreshPreview(); }, [open, refreshPreview]);

  return (
    <section aria-labelledby="traveller-welcome-heading" className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"><MessageCircle className="h-5 w-5" aria-hidden="true" /></div>
          <div>
            <h2 id="traveller-welcome-heading" className="font-semibold text-slate-950">Welcome travellers before sending documents</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">Tickets and visas go to the WhatsApp number entered for each traveller. Send the welcome to new numbers first; numbers already welcomed are skipped automatically.</p>
          </div>
        </div>
        <Button type="button" variant="outline" className="shrink-0" disabled={disabled || send.isPending || preview.isLoading} onClick={() => { send.reset(); onOpenChange(true); }}>
          Review traveller welcomes
        </Button>
      </div>
      {summary && (
        <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <WelcomeCount label="Need welcome" count={summary.needs_welcome} tone="text-amber-800" />
          <WelcomeCount label="Already welcomed" count={summary.already_welcomed} tone="text-emerald-800" />
          <WelcomeCount label="Awaiting delivery" count={summary.in_progress} tone="text-blue-800" />
          <WelcomeCount label="Need attention" count={summary.blocked} tone="text-slate-800" />
        </div>
      )}
      {preview.isLoading && <p role="status" className="mt-4 text-sm text-slate-500">Checking traveller numbers and welcome history…</p>}
      {preview.error && <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 text-sm text-red-700"><span>{preview.error.message || "Could not check traveller welcomes."}</span><Button type="button" size="sm" variant="outline" onClick={() => void preview.refetch()} disabled={preview.isFetching}><RefreshCw className="h-4 w-4" />Retry</Button></div>}
      {summary && <p className="mt-3 text-xs leading-5 text-slate-500">One welcome per WhatsApp number. Documents remain blocked until WhatsApp confirms welcome delivery. Missing or invalid traveller numbers need correction before sending.</p>}
      {feedback && <p role="status" className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{feedback}</p>}
      {open && <TravellerWelcomeDialog
        key={sourceBroadcastId ?? "default"}
        preview={preview.data}
        loading={preview.isLoading}
        refreshing={preview.isFetching}
        loadError={preview.error}
        sending={send.isPending}
        sendError={send.error}
        imagePreviewUrl={welcomeImage.image?.previewUrl}
        imageUploading={welcomeImage.uploading}
        imageError={welcomeImage.error}
        onUseOriginalImage={welcomeImage.image ? welcomeImage.clear : undefined}
        onReplaceImage={(file) => {
          const sourceId = preview.data?.source_broadcast_id;
          if (sourceId) { setSourceBroadcastId(sourceId); void welcomeImage.upload(sourceId, file); }
        }}
        onRefresh={() => void preview.refetch()}
        onSourceChange={(id) => { send.reset(); welcomeImage.clear(); setSourceBroadcastId(id); }}
        onClose={() => { if (!send.isPending && !welcomeImage.uploading) onOpenChange(false); }}
        onSend={(phoneNumbers) => {
          const data = preview.data;
          if (!data?.can_send || !data.preview_token || preview.isFetching || send.isPending || welcomeImage.uploading) return;
          send.mutate({
            phone_numbers: phoneNumbers,
            preview_token: data.preview_token,
            ...(data.source_broadcast_id ? { source_broadcast_id: data.source_broadcast_id } : {}),
            ...(welcomeImage.image ? { header_image_id: welcomeImage.image.mediaId } : {}),
          }, { onSuccess: (result) => { setFeedback(result.message); onOpenChange(false); } });
        }}
      />}
    </section>
  );
}

function WelcomeCount({ label, count, tone }: { label: string; count: number; tone: string }) {
  return <div className={`rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 ${tone}`}><div className="text-xs">{label}</div><div className="mt-1 text-xl font-semibold">{count}</div></div>;
}
