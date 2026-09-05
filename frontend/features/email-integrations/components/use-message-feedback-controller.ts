"use client";
import { useState } from "react";
import {
  useCreateEmailIntelligenceFeedback,
  useEmailReviewOptions,
  useRetryEmailIntelligence,
} from "../hooks/use-email-integrations";
import type {
  EmailAiCorrectionField,
  EmailAiCorrectionValue,
  EmailIntelligenceDetail,
} from "../types";
import {
  FeedbackCorrectionOption,
  isCorrectionReady,
  isEmailPriority,
  toLocalDateTimeInput,
} from "./message-activity-model";
type BriefStateSnapshot = {
  expected_status: "completed" | "review_required" | "ignored";
  expected_updated_at: string;
};
export function useMessageFeedbackController({
  messageId,
  intelligence,
}: {
  messageId: string;
  intelligence: EmailIntelligenceDetail;
}) {
  const feedback = useCreateEmailIntelligenceFeedback();
  const retryAnalysis = useRetryEmailIntelligence();
  const [correctionField, setCorrectionField] =
    useState<EmailAiCorrectionField | null>(null);
  const [dismissOpen, setDismissOpen] = useState(false);
  const [correctionSnapshot, setCorrectionSnapshot] =
    useState<BriefStateSnapshot | null>(null);
  const [dismissSnapshot, setDismissSnapshot] =
    useState<BriefStateSnapshot | null>(null);
  const [correctionText, setCorrectionText] = useState("");
  const [correctionNote, setCorrectionNote] = useState("");
  const [selectedIntent, setSelectedIntent] = useState(
    intelligence.intent ?? "other",
  );
  const [selectedPriority, setSelectedPriority] = useState<
    "low" | "normal" | "high" | "urgent"
  >(isEmailPriority(intelligence.priority) ? intelligence.priority : "normal");
  const [selectedGroupId, setSelectedGroupId] = useState(
    intelligence.linked_group_id ?? "",
  );
  const [selectedPassengerIds, setSelectedPassengerIds] = useState<string[]>(
    intelligence.linked_passenger_ids,
  );
  const [selectedDeadlineId, setSelectedDeadlineId] = useState("");
  const [deadlineValue, setDeadlineValue] = useState("");
  const [notificationExpected, setNotificationExpected] = useState(true);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const isLinkCorrection =
    correctionField === "linked_group" ||
    correctionField === "linked_passengers";
  const groups = useEmailReviewOptions(undefined, isLinkCorrection, messageId);
  const passengers = useEmailReviewOptions(
    selectedGroupId || undefined,
    correctionField === "linked_passengers" && Boolean(selectedGroupId),
    messageId,
  );
  const isDismissed = intelligence.status === "ignored";
  const isConfirmed = intelligence.human_review_confirmed;
  const canReview = ["completed", "review_required"].includes(
    intelligence.status,
  );
  const canCorrect = canReview || isDismissed;
  const isFailed = intelligence.status === "failed";

  function currentBriefState(): BriefStateSnapshot | null {
    if (
      intelligence.status !== "completed" &&
      intelligence.status !== "review_required" &&
      intelligence.status !== "ignored"
    ) {
      return null;
    }
    return {
      expected_status: intelligence.status,
      expected_updated_at: intelligence.updated_at,
    };
  }

  function resetCorrection() {
    setCorrectionField(null);
    setCorrectionSnapshot(null);
    setCorrectionText("");
    setCorrectionNote("");
    setSelectedIntent(intelligence.intent ?? "other");
    setSelectedPriority(
      isEmailPriority(intelligence.priority) ? intelligence.priority : "normal",
    );
    setSelectedGroupId(intelligence.linked_group_id ?? "");
    setSelectedPassengerIds(intelligence.linked_passenger_ids);
    setSelectedDeadlineId("");
    setDeadlineValue("");
    setNotificationExpected(true);
  }

  function openCorrection(option: FeedbackCorrectionOption) {
    const snapshot = currentBriefState();
    if (!snapshot) return;
    feedback.reset();
    setSuccessMessage(null);
    resetCorrection();
    setNotificationExpected(option.notificationExpected ?? true);
    setCorrectionText(
      option.field === "summary" ? (intelligence.summary ?? "") : "",
    );
    if (option.field === "deadline" && intelligence.deadlines.length === 1) {
      const [onlyDeadline] = intelligence.deadlines;
      setSelectedDeadlineId(onlyDeadline.id);
      setDeadlineValue(toLocalDateTimeInput(onlyDeadline.due_at));
    }
    setCorrectionSnapshot(snapshot);
    setCorrectionField(option.field);
  }

  function sendConfirmation() {
    const expected = currentBriefState();
    if (!expected) return;
    setSuccessMessage(null);
    feedback.reset();
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "confirmation",
          field_name: "analysis",
          ...expected,
        },
      },
      {
        onSuccess: () => {
          setSuccessMessage(
            "Review confirmed. Any separate action cards remain open.",
          );
        },
      },
    );
  }

  function sendDismissal() {
    const expected = dismissSnapshot;
    if (!expected) return;
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "dismissal",
          field_name: "analysis",
          ...expected,
        },
      },
      {
        onSuccess: () => {
          setDismissOpen(false);
          setDismissSnapshot(null);
          setSuccessMessage(
            "AI brief dismissed and removed from active AI views. The source email was not changed.",
          );
        },
      },
    );
  }

  function submitCorrection() {
    const expected = correctionSnapshot;
    if (
      correctionField === null ||
      expected === null ||
      !isCorrectionReady({
        field: correctionField,
        correctionText,
        selectedIntent,
        selectedGroupId,
        selectedDeadlineId,
        hasExistingDeadlines: intelligence.deadlines.length > 0,
        deadlineValue,
      })
    ) {
      return;
    }
    const correction: EmailAiCorrectionValue = (() => {
      if (correctionField === "summary") {
        return { text: correctionText.trim() };
      }
      if (correctionField === "intent") {
        return { intent: selectedIntent };
      }
      if (correctionField === "priority") {
        return { priority: selectedPriority };
      }
      if (correctionField === "linked_group") {
        return { group_id: selectedGroupId };
      }
      if (correctionField === "linked_passengers") {
        return { passenger_ids: selectedPassengerIds };
      }
      if (correctionField === "deadline") {
        return {
          deadline_id: selectedDeadlineId || undefined,
          due_at: new Date(deadlineValue).toISOString(),
        };
      }
      return { notification_expected: notificationExpected };
    })();
    feedback.mutate(
      {
        analysisId: intelligence.id,
        request: {
          feedback_type: "correction",
          field_name: correctionField,
          ...expected,
          correction,
          note: correctionNote.trim() || undefined,
        },
      },
      {
        onSuccess: () => {
          resetCorrection();
          setSuccessMessage(
            "Correction applied to this brief and recorded in its audit trail.",
          );
        },
      },
    );
  }

  return {
    isDismissed,
    isConfirmed,
    canCorrect,
    isFailed,
    successMessage,
    retryAnalysis,
    feedback,
    correctionField,
    dismissOpen,
    canReview,
    sendConfirmation,
    intelligence,
    openCorrection,
    currentBriefState,
    setDismissSnapshot,
    setDismissOpen,
    setSuccessMessage,
    resetCorrection,
    correctionText,
    setCorrectionText,
    selectedIntent,
    setSelectedIntent,
    selectedPriority,
    setSelectedPriority,
    selectedGroupId,
    groups,
    setSelectedGroupId,
    setSelectedPassengerIds,
    passengers,
    selectedPassengerIds,
    selectedDeadlineId,
    setSelectedDeadlineId,
    setDeadlineValue,
    deadlineValue,
    notificationExpected,
    setNotificationExpected,
    correctionNote,
    setCorrectionNote,
    submitCorrection,
    sendDismissal,
  };
}
