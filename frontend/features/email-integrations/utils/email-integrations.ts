import type { BadgeProps } from "@/components/ui";

type CollectionEnvelope<T> = {
  items: T[];
};

export type EmailOAuthCallbackNotice = {
  tone: "success" | "error";
  message: string;
};

const OAUTH_CALLBACK_MESSAGES: Record<string, EmailOAuthCallbackNotice> = {
  connected: {
    tone: "success",
    message: "Gmail was connected successfully. Inbox monitoring will begin shortly.",
  },
  reconnected: {
    tone: "success",
    message: "Gmail access was restored successfully.",
  },
  cancelled: {
    tone: "error",
    message: "Gmail connection was cancelled. No account access was granted.",
  },
  denied: {
    tone: "error",
    message: "Gmail access was not granted. You can try connecting again.",
  },
  failed: {
    tone: "error",
    message: "Gmail could not be connected. Please try again.",
  },
};

export function normalizeEmailCollection<T>(
  value: T[] | CollectionEnvelope<T>,
): T[] {
  return Array.isArray(value) ? value : value.items;
}

export function formatEmailLabel(value: string | null | undefined): string {
  if (!value) return "Not available";
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function emailStatusVariant(
  status: string | null | undefined,
): BadgeProps["variant"] {
  switch (status) {
    case "active":
    case "completed":
    case "matched":
    case "relevant":
    case "approved":
      return "success";
    case "syncing":
    case "disconnecting":
    case "processing":
    case "pending":
    case "open":
    case "review":
    case "review_required":
    case "deferred":
      return "warning";
    case "expired":
    case "failing":
    case "failed":
    case "error":
    case "blocked":
    case "disconnected":
    case "rejected":
      return "destructive";
    case "paused":
    case "ignored":
    case "unrelated":
      return "outline";
    default:
      return "default";
  }
}

export function isSafeOAuthAuthorizationUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && Boolean(url.hostname);
  } catch {
    return false;
  }
}

export function readEmailOAuthCallback(
  search: string,
): EmailOAuthCallbackNotice | null {
  const params = new URLSearchParams(search);
  const rawStatus =
    params.get("email_oauth")
    ?? params.get("oauth_status")
    ?? params.get("connection_status");
  return rawStatus ? OAUTH_CALLBACK_MESSAGES[rawStatus] ?? null : null;
}

export function cleanEmailOAuthCallbackUrl(url: URL): string {
  const cleaned = new URL(url);
  cleaned.searchParams.delete("email_oauth");
  cleaned.searchParams.delete("oauth_status");
  cleaned.searchParams.delete("connection_status");
  cleaned.searchParams.delete("code");
  cleaned.searchParams.delete("state");
  cleaned.searchParams.delete("error");
  const query = cleaned.searchParams.toString();
  return `${cleaned.pathname}${query ? `?${query}` : ""}${cleaned.hash}`;
}

export function isEmailProcessingActive(status: string): boolean {
  return ["received", "queued", "processing", "retrieving", "matching"].includes(
    status.toLowerCase(),
  );
}
