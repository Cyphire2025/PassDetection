import { Building2, Mail, UserRound, type LucideIcon } from "lucide-react";
import type { EmailAiRolloutScope, EmailAiRolloutTarget } from "../types";
import { readEmailActionError } from "../utils/email-integrations";

export const ROLLOUT_SCOPES: ReadonlyArray<{
  value: EmailAiRolloutScope;
  label: string;
  singular: string;
  description: string;
  icon: LucideIcon;
}> = [
    {
      value: "agency",
      label: "Agencies",
      singular: "agency",
      description: "Pause or allow an entire agency",
      icon: Building2,
    },
    {
      value: "user",
      label: "Users",
      singular: "user",
      description: "Control one mailbox owner",
      icon: UserRound,
    },
    {
      value: "connection",
      label: "My mailboxes",
      singular: "mailbox",
      description: "Control one of your connected mailboxes",
      icon: Mail,
    },
  ];

export type RolloutNotice = {
  tone: "success" | "error" | "warning" | "info";
  message: string;
};

export type RolloutDecision = {
  target: EmailAiRolloutTarget;
  enabled: boolean;
};

export function nextDirectEnabled(target: EmailAiRolloutTarget) {
  if (target.direct_enabled !== null) return !target.direct_enabled;
  return !target.effective_enabled;
}

export function rolloutExplanation(target: EmailAiRolloutTarget) {
  if (target.direct_enabled === false) {
    return "Paused directly at this level.";
  }
  if (target.direct_enabled === true && !target.effective_enabled) {
    return "Allowed here, but a global or parent pause still applies.";
  }
  if (target.direct_enabled === true) {
    return "Allowed here and not blocked by a parent setting.";
  }
  return target.effective_enabled
    ? "Inherited from the current parent rollout settings."
    : "Inherited, with a global or parent pause currently applying.";
}

export function scopeSingular(scopeType: EmailAiRolloutScope) {
  return (
    ROLLOUT_SCOPES.find((scope) => scope.value === scopeType)?.singular
    ?? "rollout scope"
  );
}

export function readRolloutError(error: unknown) {
  if (isRolloutConflict(error)) {
    return "This rollout control changed elsewhere. Close this window, review the refreshed state, and try again.";
  }
  return readEmailActionError(error, "The rollout control could not be saved. Refresh and try again.");
}

export function isRolloutConflict(error: unknown) {
  return (
    typeof error === "object"
    && error !== null
    && "code" in error
    && error.code === "HTTP_409"
  );
}
