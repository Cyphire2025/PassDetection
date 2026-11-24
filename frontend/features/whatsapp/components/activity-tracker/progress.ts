import { whatsappAwaitingReceiptCount } from "../../utils/batch-polling";
import { type DisplayedWhatsAppActivity, whatsappActivitySourceHref } from "../../utils/activity-tracking";

export function describeWhatsAppActivity(activity: DisplayedWhatsAppActivity, showFailures: boolean) {
  const isRunning = activity.queued > 0;
  const awaitingReceipt = whatsappAwaitingReceiptCount(activity.status_counts, activity.sent);
  const delivered = (activity.status_counts?.delivered ?? 0) + (activity.status_counts?.read ?? 0);
  const isAwaitingReceipt = awaitingReceipt > 0;
  const needsAttention = activity.failed > 0 || activity.delivery_unknown > 0;
  const deliveryTotal = Math.max(0, activity.total - activity.failed);
  const outcomeLabel = activity.total > 0 && deliveryTotal === 0
    ? "All messages failed"
    : activity.status_counts
      ? `${delivered.toLocaleString()} delivered of ${deliveryTotal.toLocaleString()}`
      : `${activity.sent.toLocaleString()} accepted of ${deliveryTotal.toLocaleString()}`;
  const pendingStatusLabel = [
    activity.queued > 0 ? `${activity.queued.toLocaleString()} queued` : null,
    isAwaitingReceipt ? `${awaitingReceipt.toLocaleString()} awaiting delivery confirmation` : null,
  ].filter(Boolean).join(" · ");
  const completedCount = Math.max(
    0,
    activity.total - activity.queued,
  );
  const progressPercent =
    activity.total > 0
      ? Math.min(100, Math.round((completedCount / activity.total) * 100))
      : 0;
  const sourceHref = whatsappActivitySourceHref(activity);
  const skipCount =
    activity.skipped_already_sent
    + activity.skipped_in_progress
    + activity.skipped_delivery_unknown;
  const hasExpandedContent =
    skipCount > 0
    || activity.delivery_unknown > 0
    || (showFailures && activity.failed > 0);
  return {
    isRunning,
    isAwaitingReceipt,
    needsAttention,
    delivered,
    outcomeLabel,
    pendingStatusLabel,
    completedCount,
    progressPercent,
    sourceHref,
    skipCount,
    hasExpandedContent,
  };
}
