"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui";
import { GcDialog } from "../components/gc-dialog";
import { GcAlert } from "../components/gc-app-feedback";
import { formatGcDateTime } from "../utils";
import type { NotificationDraft, NotificationPreview } from "./notification-types";

export function NotificationReviewDialog({ draft, preview, busy, recovering, resending, error, onClose, onRefresh, onSend }: {
  draft: NotificationDraft;
  preview: NotificationPreview;
  busy: boolean;
  recovering: boolean;
  resending: boolean;
  error?: string | null;
  onClose: () => void;
  onRefresh: () => void;
  onSend: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1_000); return () => clearInterval(timer); }, []);
  const expired = !Number.isFinite(Date.parse(preview.expires_at)) || now >= Date.parse(preview.expires_at);
  const unavailableGroups = draft.audience === "selected_groups" ? draft.group_ids.flatMap((id, index) => preview.group_ids.includes(id) ? [] : [draft.group_names?.[index] ?? `Selected trip ${index + 1}`]) : [];
  return <GcDialog open title={recovering ? "Review the previous send request" : "Review phone notification"} description="Check the message and audience before sending." onClose={onClose} closeDisabled={busy} footer={<>
    <Button type="button" variant="secondary" disabled={busy} onClick={onClose}>Back to editor</Button>
    <Button type="button" variant="secondary" disabled={busy} onClick={onRefresh}>Refresh audience</Button>
    <Button type="button" isLoading={busy} disabled={expired || preview.recipient_count === 0 || unavailableGroups.length > 0} onClick={onSend}>{recovering ? "Retry same send request" : resending ? "Send again" : "Send notification"}</Button>
  </>}>
    <div className="space-y-4">
      {error && <GcAlert message={error} />}
      {!preview.provider_enabled && <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Phone delivery is disabled on the server. Sending records the notification, but a phone alert cannot be delivered while the provider remains disabled.</p>}
      {preview.provider_enabled && (!preview.android_provider_enabled || !preview.ios_provider_enabled) && <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">Phone delivery is enabled for {preview.android_provider_enabled ? "Android" : "iOS"} only. {preview.android_provider_enabled ? "iOS" : "Android"} alerts cannot be delivered while that provider is disabled.</p>}
      {preview.eligible_device_count === 0 && <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">There are no eligible registered devices. This send cannot reach a phone right now.</p>}
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4" aria-label="Phone alert preview">
        <p className="text-xs font-medium text-slate-500">GC App · notification preview</p>
        <h3 className="mt-2 break-words font-semibold text-slate-900">{draft.title}</h3>
        <p className="mt-1 whitespace-pre-wrap break-words text-sm text-slate-700">{draft.body}</p>
      </div>
      <div className="space-y-3 text-sm text-slate-700">
        <h3 className="font-semibold text-slate-900">{draft.audience === "all_active_trips" ? "All active GC App trips" : "Specific groups"}</h3>
        <dl className="grid grid-cols-2 gap-3">
          <ReviewCount label="Active trips" count={preview.group_count} />
          <ReviewCount label="Eligible recipients" count={preview.recipient_count} />
          <ReviewCount label="Passengers" count={preview.role_counts.passengers} />
          <ReviewCount label="Client Managers" count={preview.role_counts.client_managers} />
          <ReviewCount label="Coordinators" count={preview.role_counts.coordinators} />
          <ReviewCount label="Eligible registered devices" count={preview.eligible_device_count} />
          <ReviewCount label="Recipients without an active device" count={preview.no_active_registration_count} />
        </dl>
        <details className="rounded-lg border border-slate-200 p-3"><summary className="cursor-pointer font-medium">Included trips ({preview.group_count})</summary><ul className="mt-2 list-inside list-disc space-y-1">{preview.group_names.map((name, index) => <li key={preview.group_ids[index] ?? index}>{name}</li>)}</ul></details>
      </div>
      {preview.recipient_count === 0 && <p role="alert" className="text-sm text-red-700">No currently authorized app users are eligible. Choose another audience or review trip access first.</p>}
      {unavailableGroups.length > 0 && <p role="alert" className="text-sm text-red-700">These selected trips are no longer available to this audience: {unavailableGroups.join(", ")}. Return to the editor and review your selection before sending.</p>}
      {expired && <p role="alert" className="text-sm text-red-700">This review has expired. Refresh the audience before sending.</p>}
      <p className="text-xs leading-5 text-slate-500">This review is valid until {formatGcDateTime(preview.expires_at)}. The delivery window lasts {preview.delivery_window_hours} hours, while recipients remain eligible. Phone permissions, connectivity and device settings affect whether an alert appears.</p>
      {resending && <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This is a new deliberate send. People who received the earlier alert can receive it again.</p>}
      {recovering && <p className="rounded-lg bg-blue-50 p-3 text-sm text-blue-900">The original request reference is reused. This action checks or completes that request without creating a second send.</p>}
    </div>
  </GcDialog>;
}

function ReviewCount({ label, count }: { label: string; count: number }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 text-lg font-semibold text-slate-900">{count}</dd></div>;
}
