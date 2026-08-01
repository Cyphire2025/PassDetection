import type {
  WhatsAppBatchSummary,
  WhatsAppSendResponse,
} from "../api/whatsapp.api";

export type WhatsAppInitialSkipCounts = {
  skipped_already_sent?: number;
  skipped_in_progress?: number;
  skipped_delivery_unknown?: number;
};

export type WhatsAppSendProgress = Pick<
  WhatsAppSendResponse,
  "queued" | "sent" | "failed" | "delivery_unknown"
> & {
  batch_id?: string | null;
  skipped_already_sent: number;
  skipped_in_progress: number;
  skipped_delivery_unknown: number;
};

export function mergeWhatsAppSendProgress(
  currentBatch: WhatsAppBatchSummary | WhatsAppSendResponse | null | undefined,
  initialSend: WhatsAppSendResponse | null | undefined,
  persistedSkips?: WhatsAppInitialSkipCounts | null,
): WhatsAppSendProgress | WhatsAppSendResponse | null {
  if (!currentBatch) return initialSend ?? null;
  const currentSkips =
    "skipped_already_sent" in currentBatch ? currentBatch : null;

  return {
    ...currentBatch,
    skipped_already_sent: Math.max(
      currentSkips?.skipped_already_sent ?? 0,
      initialSend?.skipped_already_sent ?? 0,
      persistedSkips?.skipped_already_sent ?? 0,
    ),
    skipped_in_progress: Math.max(
      currentSkips?.skipped_in_progress ?? 0,
      initialSend?.skipped_in_progress ?? 0,
      persistedSkips?.skipped_in_progress ?? 0,
    ),
    skipped_delivery_unknown: Math.max(
      currentSkips?.skipped_delivery_unknown ?? 0,
      initialSend?.skipped_delivery_unknown ?? 0,
      persistedSkips?.skipped_delivery_unknown ?? 0,
    ),
  };
}
