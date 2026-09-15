import { gcAppErrorMessage } from "../utils";

const labels: Record<string, string> = {
  draft_conflict: "This saved message changed. Reload it before reviewing another send; your editor text is kept.",
  stale_preview: "This audience review has expired. Review the current audience again before sending.",
  audience_changed: "Trip availability or recipient access has changed. Check your selected trips and their access, then review the audience again before sending.",
  idempotency_conflict: "This send request already belongs to a different review. Check its recorded outcome before starting another send.",
  no_eligible_recipients: "No currently authorized app users are eligible for this audience.",
};

export function notificationError(error: unknown, fallback: string): string {
  const text = gcAppErrorMessage(error, fallback);
  return labels[text] ?? text;
}

export function isNotFound(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && error.status === 404;
}

export function isRejectedBeforeSend(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("status" in error) || error.status !== 409 || !("message" in error)) return false;
  // These responses follow the server's lookup for an already recorded request.
  // Keep all ambiguous errors, including stale/invalid tokens, in recovery.
  return error.message === "audience_changed" || error.message === "draft_conflict" || error.message === "no_eligible_recipients";
}
