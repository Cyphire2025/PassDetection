import type {
  EmailActiveDeadlineStatus,
  EmailAiCorrectionField,
  EmailDeadlineDecisionAction,
  EmailIntelligenceDetail,
  EmailProposalDecisionAction,
} from "../types";
export function proposalActionLabel(action: EmailProposalDecisionAction) {
  if (action === "approve") return "Approve";
  if (action === "reject") return "Reject";
  return "Dismiss";
}

export interface FeedbackCorrectionOption {
  field: EmailAiCorrectionField;
  buttonLabel: string;
  notificationExpected?: boolean;
}

export function feedbackCorrectionOptions(
  intelligence: EmailIntelligenceDetail,
) {
  const options: FeedbackCorrectionOption[] = [
    { field: "summary", buttonLabel: "Correct summary" },
    { field: "intent", buttonLabel: "Wrong category" },
    { field: "priority", buttonLabel: "Wrong priority" },
  ];
  options.push({
    field: "linked_group",
    buttonLabel: intelligence.linked_group_name
      ? "Wrong group"
      : "Add missing group",
  });
  options.push({
    field: "linked_passengers",
    buttonLabel: intelligence.linked_passengers.length
      ? "Wrong passenger"
      : "Add missing passenger",
  });
  options.push({
    field: "deadline",
    buttonLabel: intelligence.deadlines.length
      ? "Wrong deadline"
      : "Add missing deadline",
  });
  options.push(
    {
      field: "notification",
      buttonLabel: "Should have notified me",
      notificationExpected: true,
    },
    {
      field: "notification",
      buttonLabel: "Should not notify me",
      notificationExpected: false,
    },
  );
  return options;
}

export function feedbackCorrectionCopy(field: EmailAiCorrectionField) {
  const copy: Record<EmailAiCorrectionField, { title: string }> = {
    summary: {
      title: "Correct the operational summary",
    },
    linked_group: {
      title: "Select the correct group",
    },
    linked_passengers: {
      title: "Select the correct passengers",
    },
    intent: {
      title: "Correct the email category",
    },
    priority: {
      title: "Correct the priority",
    },
    deadline: {
      title: "Correct the deadline",
    },
    notification: {
      title: "Correct the notification expectation",
    },
  };
  return copy[field];
}

export const EMAIL_INTENT_OPTIONS = [
  "document_submission",
  "document_request",
  "itinerary_update",
  "itinerary_change",
  "visa_status",
  "information_request",
  "action_request",
  "deadline_notice",
  "deadline_update",
  "cancellation",
  "payment",
  "general_travel",
  "other",
] as const;

export function isEmailPriority(
  value: string | null,
): value is "low" | "normal" | "high" | "urgent" {
  return value !== null && ["low", "normal", "high", "urgent"].includes(value);
}

export function isCorrectionReady({
  field,
  correctionText,
  selectedIntent,
  selectedGroupId,
  selectedDeadlineId,
  hasExistingDeadlines,
  deadlineValue,
}: {
  field: EmailAiCorrectionField;
  correctionText: string;
  selectedIntent: string;
  selectedGroupId: string;
  selectedDeadlineId: string;
  hasExistingDeadlines: boolean;
  deadlineValue: string;
}) {
  if (field === "summary") return Boolean(correctionText.trim());
  if (field === "intent") return Boolean(selectedIntent);
  if (field === "linked_group" || field === "linked_passengers") {
    return Boolean(selectedGroupId);
  }
  if (field === "deadline") {
    return (
      (!hasExistingDeadlines || Boolean(selectedDeadlineId)) &&
      Boolean(deadlineValue) &&
      !Number.isNaN(Date.parse(deadlineValue))
    );
  }
  return true;
}

export function toLocalDateTimeInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function isActiveDeadlineStatus(
  value: string,
): value is EmailActiveDeadlineStatus {
  return ["detected", "review_required", "acknowledged"].includes(value);
}

export function deadlineActionLabel(action: EmailDeadlineDecisionAction) {
  if (action === "acknowledge") return "Acknowledge";
  if (action === "complete") return "Mark complete";
  return "Dismiss";
}

export function readActionError(error: unknown, fallback: string) {
  if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message.slice(0, 300);
  }
  return fallback;
}
