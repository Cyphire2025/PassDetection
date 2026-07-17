import type { WhatsAppSendResponse } from "../api/whatsapp.api";

export type WhatsAppInitialSkipCounts = {
  skipped_already_sent?: number;
  skipped_in_progress?: number;
  skipped_delivery_unknown?: number;
};

export function mergeWhatsAppSendProgress(
  currentBatch: WhatsAppSendResponse | null | undefined,
  initialSend: WhatsAppSendResponse | null | undefined,
  persistedSkips?: WhatsAppInitialSkipCounts | null,
): WhatsAppSendResponse | null {
  if (!currentBatch) return initialSend ?? null;

  return {
    ...currentBatch,
    skipped_already_sent: Math.max(
      currentBatch.skipped_already_sent ?? 0,
      initialSend?.skipped_already_sent ?? 0,
      persistedSkips?.skipped_already_sent ?? 0,
    ),
    skipped_in_progress: Math.max(
      currentBatch.skipped_in_progress ?? 0,
      initialSend?.skipped_in_progress ?? 0,
      persistedSkips?.skipped_in_progress ?? 0,
    ),
    skipped_delivery_unknown: Math.max(
      currentBatch.skipped_delivery_unknown ?? 0,
      initialSend?.skipped_delivery_unknown ?? 0,
      persistedSkips?.skipped_delivery_unknown ?? 0,
    ),
  };
}
