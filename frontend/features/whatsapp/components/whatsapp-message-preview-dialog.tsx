"use client";

import { Button, Input } from "@/components/ui";
import { Bold, CheckCircle2, Info, Send, Upload, UsersRound } from "lucide-react";
import Image from "next/image";
import {
  type Dispatch,
  type FormEvent,
  type SetStateAction,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  WhatsAppBroadcastGroup,
  WhatsAppBulkResendOverrides,
  WhatsAppBulkResendPreviewResponse,
  WhatsAppMessageType,
  WhatsAppPreviewResponse,
  WhatsAppRecipient,
  WhatsAppReminderAudience,
} from "../api/whatsapp.api";
import {
  usePreviewWhatsAppMessage,
  usePreviewWhatsAppBulkResendMessage,
  useWhatsAppGroup,
} from "../hooks/use-whatsapp";
import {
  canRetryOrResendRecipient,
  isRecipientEligible,
  welcomeDeliveryBlockReason,
} from "../utils/recipient-delivery";
import { toggleWhatsAppBold } from "../utils/whatsapp-formatting";
import { MessageComposerSection, MessageDeliveryPreview } from "./whatsapp-message-composer-ui";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import type { RecipientResendTarget } from "./whatsapp-workspace.types";
import { WhatsAppBroadcastMotion } from "./whatsapp-broadcast-motion";
import { RecipientBulkComposerAudience } from "./whatsapp-bulk-composer-audience";
import { ReminderAudienceSelector } from "./whatsapp-reminder-audience";

const MAX_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024;
const WELCOME_IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);

export type MessagePreviewSendPayload = {
  passportIntro: string;
  passportLink: string;
  messageContent: string;
  headerImage: File | null;
  headerImageId: string | null;
  recipientIds: string[] | null;
  supportContactIds: string[] | null;
  reminderAudience?: WhatsAppReminderAudience;
  reminderAudienceClientGroupId?: string | null;
  bulkDraft?: WhatsAppBulkResendOverrides;
};

export function MessagePreviewDialog({
  group,
  messageType,
  targetRecipient,
  bulkRecipients,
  hiddenSelectedCount = 0,
  isSending,
  onClose,
  onSend,
}: {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
  targetRecipient?: RecipientResendTarget;
  bulkRecipients?: WhatsAppRecipient[];
  hiddenSelectedCount?: number;
  isSending: boolean;
  onClose: () => void;
  onSend: (payload: MessagePreviewSendPayload) => Promise<void>;
}) {
  const { data: detail, isLoading: isLoadingDetail } = useWhatsAppGroup(
    group.id,
  );
  const previewRequest = usePreviewWhatsAppMessage();
  const bulkPreviewRequest = usePreviewWhatsAppBulkResendMessage();
  const bulkMode = bulkRecipients !== undefined;
  const bulkRecipientIds = useMemo(() => bulkRecipients?.map((recipient) => recipient.id) ?? null, [bulkRecipients]);
  const [passportIntro, setPassportIntro] = useState<string | null>(null);
  const [passportLink, setPassportLink] = useState<string | null>(null);
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [headerImage, setHeaderImage] = useState<File | null>(null);
  const [headerImageId, setHeaderImageId] = useState<string | null>(null);
  const [headerImagePreview, setHeaderImagePreview] = useState<string | null>(
    null,
  );
  const [previewRecipientId, setPreviewRecipientId] = useState<string | null>(
    targetRecipient?.recipientId ?? null,
  );
  const [recipientSearch, setRecipientSearch] = useState("");
  const [recipientSelectionMode, setRecipientSelectionMode] = useState<
    "all" | "custom"
  >("all");
  const [selectedRecipientIds, setSelectedRecipientIds] = useState<string[]>(
    [],
  );
  const [reminderAudience, setReminderAudience] = useState<WhatsAppReminderAudience>("all");
  const [reminderAudienceClientGroupId, setReminderAudienceClientGroupId] = useState<string | null>(null);
  const [selectedSupportContactIds, setSelectedSupportContactIds] = useState<
    string[] | null
  >(null);
  const [previewRetryAttempt, setPreviewRetryAttempt] = useState(0);
  const [previewedRequestKey, setPreviewedRequestKey] = useState<string | null>(
    null,
  );
  const [headerImageRevision, setHeaderImageRevision] = useState(0);
  const [preview, setPreview] = useState<WhatsAppPreviewResponse | null>(null);
  const [bulkPreview, setBulkPreview] = useState<WhatsAppBulkResendPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submissionStartedAt, setSubmissionStartedAt] = useState<number | null>(null);
  const [bulkRecovery, setBulkRecovery] = useState<{ draftKey: string; payload: MessagePreviewSendPayload } | null>(null);
  const submissionPending = submissionStartedAt !== null || isSending;
  const previewSequence = useRef(0);
  const sendInFlightRef = useRef(false);
  const headerImagePreviewUrlRef = useRef<string | null>(null);
  const passportIntroRef = useRef<HTMLTextAreaElement>(null);
  const messageContentRef = useRef<HTMLTextAreaElement>(null);
  const passportIntroId = useId();
  const messageContentId = useId();
  const previewMutate = previewRequest.mutate;
  const bulkPreviewMutate = bulkPreviewRequest.mutate;
  const previewPending = bulkMode ? bulkPreviewRequest.isPending : previewRequest.isPending;
  const linkedClientGroups = (detail?.linked_client_groups ?? []).filter(
    (clientGroup) => clientGroup.status === "active",
  );
  const previewDetailRevision = useMemo(() => (
    detail
      ? JSON.stringify({
          updatedAt: detail.updated_at,
          recipientOptInConfirmed: detail.recipient_opt_in_confirmed,
          linkedClientGroups: (detail.linked_client_groups ?? []).map((clientGroup) => [
            clientGroup.id,
            clientGroup.status,
          ]),
          recipients: detail.recipients.map((recipient) => ({
            id: recipient.id,
            name: recipient.name,
            phone: recipient.normalized_phone_number,
            welcomeStatus: recipient.welcome_status,
            welcomeDelivered: recipient.welcome_delivered,
            welcomeRequiredReason: recipient.welcome_required_reason,
            messageStatuses: recipient.message_statuses.map((messageStatus) => [
              messageStatus.message_type,
              messageStatus.status,
              messageStatus.latest_resend_status,
              messageStatus.resend_blocked,
              messageStatus.status_updated_at,
            ]),
          })),
        })
      : null
  ), [detail]);
  const selectedActiveReminderGroupId = reminderAudienceClientGroupId
    && linkedClientGroups.some((clientGroup) => (
      clientGroup.id === reminderAudienceClientGroupId
    ))
    ? reminderAudienceClientGroupId
    : null;
  const resolvedReminderAudienceClientGroupId = reminderAudience === "not_submitted"
    ? selectedActiveReminderGroupId
      ?? (linkedClientGroups.length === 1 ? linkedClientGroups[0]?.id ?? null : null)
    : null;
  const reminderAudienceSelectionReady = messageType !== "reminder"
    || reminderAudience === "all"
    || Boolean(resolvedReminderAudienceClientGroupId);
  const resolvedSupportContactIds = useMemo(() => {
    if (selectedSupportContactIds !== null) {
      return selectedSupportContactIds.slice(0, 1);
    }
    const firstContactId = detail?.support_contacts[0]?.id;
    return firstContactId ? [firstContactId] : [];
  }, [detail?.support_contacts, selectedSupportContactIds]);

  useEffect(() => {
    return () => {
      if (headerImagePreviewUrlRef.current) {
        URL.revokeObjectURL(headerImagePreviewUrlRef.current);
      }
    };
  }, []);

  const replaceHeaderImage = (image: File | null) => {
    if (headerImagePreviewUrlRef.current) {
      URL.revokeObjectURL(headerImagePreviewUrlRef.current);
    }
    const previewUrl = image ? URL.createObjectURL(image) : null;
    headerImagePreviewUrlRef.current = previewUrl;
    setHeaderImage(image);
    setHeaderImageRevision((revision) => revision + 1);
    setHeaderImagePreview(previewUrl);
    if (image) setHeaderImageId(null);
  };

  const applyBoldFormatting = (
    textarea: HTMLTextAreaElement | null,
    value: string,
    setValue: Dispatch<SetStateAction<string | null>>,
  ) => {
    if (!textarea) return;
    const update = toggleWhatsAppBold(
      value,
      textarea.selectionStart,
      textarea.selectionEnd,
    );
    if (update.value.length > 600) {
      setError(
        "Bold formatting must fit within the 600-character message limit.",
      );
      return;
    }
    setValue(update.value);
    window.requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(update.selectionStart, update.selectionEnd);
    });
  };

  // The key changes during render, before the preview debounce starts. A prior
  // success can never authorize edited wording, a changed image, or recipients.
  const previewRequestKey = JSON.stringify({
    groupId: group.id,
    messageType,
    passportIntro,
    passportLink,
    messageContent,
    headerImageId,
    headerImageRevision,
    previewRecipientId,
    recipientSelectionMode,
    selectedRecipientIds,
    reminderAudience,
    reminderAudienceClientGroupId: resolvedReminderAudienceClientGroupId,
    supportContactIds: bulkMode ? selectedSupportContactIds : resolvedSupportContactIds,
    bulkRecipientIds,
    resendRecipientId: targetRecipient?.recipientId ?? null,
    detailRevision: previewDetailRevision,
  });
  const previewIsCurrent = Boolean(
    preview && previewedRequestKey === previewRequestKey,
  );

  useEffect(() => {
    const sequence = ++previewSequence.current;
    const controller = new AbortController();
    if (!reminderAudienceSelectionReady) {
      return () => controller.abort();
    }
    const timeout = window.setTimeout(() => {
      if (bulkMode && bulkRecipientIds && messageType !== "reminder") {
        bulkPreviewMutate({
          groupId: group.id,
          messageType,
          recipientIds: bulkRecipientIds,
          previewRecipientId,
          overrides: {
            messageContent,
            passportIntro: messageType === "passport_link" ? passportIntro : null,
            headerImageId,
            supportContactIds: messageType === "passport_link" ? selectedSupportContactIds : null,
          },
          signal: controller.signal,
        }, {
          onSuccess: (response) => {
            if (controller.signal.aborted || sequence !== previewSequence.current) return;
            setPreview(response);
            setBulkPreview(response);
            setPreviewedRequestKey(previewRequestKey);
            // Saved values remain preview fallbacks. Only staff edits become
            // overrides shared with the other selected recipients.
            setError(null);
          },
          onError: (previewError) => {
            if (controller.signal.aborted || sequence !== previewSequence.current) return;
            setPreviewedRequestKey(null);
            setError(readErrorMessage(previewError, "Could not generate the selected recipients’ resend preview."));
          },
        });
        return;
      }
      previewMutate(
        {
          groupId: group.id,
          draft: {
            message_type: messageType,
            passport_intro:
              messageType === "passport_link" ? passportIntro : null,
            passport_link:
              messageType === "passport_link" ? passportLink : null,
            message_content: messageContent,
            recipient_id: targetRecipient ? null : previewRecipientId,
            resend_recipient_id: targetRecipient?.recipientId ?? null,
            header_image_id: headerImageId,
            recipient_ids:
              messageType === "passport_link" &&
              !targetRecipient &&
              recipientSelectionMode === "custom"
                ? selectedRecipientIds
                : null,
            support_contact_ids:
              messageType === "passport_link" && detail
                ? resolvedSupportContactIds
                : null,
            ...(messageType === "reminder" ? {
              audience: reminderAudience,
              audience_client_group_id: resolvedReminderAudienceClientGroupId,
            } : {}),
          },
          signal: controller.signal,
        },
        {
          onSuccess: (response) => {
            if (
              controller.signal.aborted ||
              sequence !== previewSequence.current
            )
              return;
            setPreview(response);
            setPreviewedRequestKey(previewRequestKey);
            setPassportIntro(
              (current) => current ?? response.passport_intro ?? null,
            );
            setPassportLink(
              (current) => current ?? response.passport_link ?? null,
            );
            setMessageContent((current) => current ?? response.message_content);
            setHeaderImageId((current) =>
              headerImage
                ? current
                : (current ?? response.header_image_id ?? null),
            );
            setError(null);
          },
          onError: (previewError) => {
            if (
              controller.signal.aborted ||
              sequence !== previewSequence.current
            )
              return;
            setPreviewedRequestKey(null);
            setError(
              readErrorMessage(
                previewError,
                "Could not generate the WhatsApp preview.",
              ),
            );
          },
        },
      );
    }, 250);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [
    previewRetryAttempt,
    previewRequestKey,
    group.id,
    detail,
    headerImage,
    headerImageId,
    messageContent,
    messageType,
    passportIntro,
    passportLink,
    previewMutate,
    previewRecipientId,
    recipientSelectionMode,
    selectedRecipientIds,
    reminderAudience,
    resolvedReminderAudienceClientGroupId,
    reminderAudienceSelectionReady,
    resolvedSupportContactIds,
    targetRecipient,
    bulkMode,
    bulkRecipientIds,
    bulkPreviewMutate,
    selectedSupportContactIds,
  ]);

  const resolvedMessageContent = (
    messageContent ??
    preview?.message_content ??
    ""
  ).trim();
  const resolvedPassportIntro = (
    passportIntro ??
    preview?.passport_intro ??
    ""
  ).trim();
  const resolvedPassportLink = (
    passportLink ??
    preview?.passport_link ??
    ""
  ).trim();
  const effectiveHeaderImageId = headerImageId ?? (bulkMode ? preview?.header_image_id ?? null : null);
  const hasHeaderImage = Boolean(headerImage || effectiveHeaderImageId);
  const targetRecipientDetail =
    targetRecipient && detail
      ? detail.recipients.find(
          (recipient) => recipient.id === targetRecipient.recipientId,
        )
      : undefined;
  const canResendTarget =
    !targetRecipient ||
    Boolean(
      targetRecipientDetail && canRetryOrResendRecipient(targetRecipientDetail, messageType, targetRecipient.action),
    );
  const eligibleRecipients = useMemo(
    () =>
      detail?.recipients.filter((recipient) =>
        isRecipientEligible(recipient, messageType),
      ) ?? [],
    [detail?.recipients, messageType],
  );
  const selectedRecipientIdSet = useMemo(
    () => new Set(selectedRecipientIds),
    [selectedRecipientIds],
  );
  const selectedEligibleRecipients = useMemo(
    () =>
      messageType === "passport_link" &&
      !targetRecipient &&
      recipientSelectionMode === "custom"
        ? eligibleRecipients.filter((recipient) =>
            selectedRecipientIdSet.has(recipient.id),
          )
        : eligibleRecipients,
    [
      eligibleRecipients,
      messageType,
      recipientSelectionMode,
      selectedRecipientIdSet,
      targetRecipient,
    ],
  );
  const usesNotSubmittedAudience = messageType === "reminder"
    && !targetRecipient
    && !bulkMode
    && reminderAudience === "not_submitted";
  const currentPreviewEligibleCount = previewIsCurrent
    ? preview?.eligible_recipient_count
    : undefined;
  const bulkWelcomeBlockedIds = useMemo(() => {
    const currentRecipients = new Map(detail?.recipients.map((recipient) => [recipient.id, recipient]));
    return new Set((bulkRecipients ?? []).filter((recipient) =>
      welcomeDeliveryBlockReason(currentRecipients.get(recipient.id) ?? recipient, messageType),
    ).map((recipient) => recipient.id));
  }, [bulkRecipients, detail?.recipients, messageType]);
  const eligibleRecipientCount = bulkMode
    ? (bulkPreview?.eligible_recipient_ids.filter((id) => !bulkWelcomeBlockedIds.has(id)).length ?? 0)
    : targetRecipient
    ? 1
    : recipientSelectionMode === "custom"
      ? selectedEligibleRecipients.length
      : usesNotSubmittedAudience
        ? currentPreviewEligibleCount ?? 0
        : (currentPreviewEligibleCount ??
        (detail ? eligibleRecipients.length : undefined) ??
        group.recipient_count);
  const audienceRecipientCount = previewIsCurrent
    ? preview?.audience_recipient_count
      ?? (reminderAudience === "all" ? preview?.recipient_count ?? group.recipient_count : null)
    : null;
  const excludedSubmittedCount = previewIsCurrent
    ? preview?.excluded_submitted_count ?? 0
    : 0;
  const excludedNeedsReviewCount = previewIsCurrent
    ? preview?.excluded_needs_review_count ?? 0
    : 0;
  const reminderAudienceConfirmed = messageType !== "reminder"
    || targetRecipient !== undefined
    || reminderAudience === "all"
    || (
      preview?.audience === "not_submitted"
      && preview.audience_client_group_id === resolvedReminderAudienceClientGroupId
      && typeof preview.audience_recipient_count === "number"
      && typeof preview.excluded_submitted_count === "number"
      && typeof preview.excluded_needs_review_count === "number"
    );
  const previewWelcomeRequiredCount = (bulkMode ? bulkPreview : preview)?.welcome_required_count ?? 0;
  const welcomeGateReason = previewWelcomeRequiredCount > 0
    ? (bulkMode ? bulkPreview : preview)?.welcome_required_reason
      || `${previewWelcomeRequiredCount} selected numbers need confirmed welcome delivery before other messages can be sent.`
    : targetRecipientDetail
      ? welcomeDeliveryBlockReason(targetRecipientDetail, messageType)
      : null;
  const canSend = Boolean(
    previewIsCurrent &&
      !previewPending &&
      detail?.recipient_opt_in_confirmed &&
      (messageType !== "passport_link" ||
        (bulkMode && selectedSupportContactIds === null) || resolvedSupportContactIds.length > 0) &&
      resolvedMessageContent &&
      eligibleRecipientCount > 0 &&
      reminderAudienceSelectionReady &&
      reminderAudienceConfirmed &&
      canResendTarget &&
      !welcomeGateReason &&
      (messageType === "reminder" || hasHeaderImage) &&
      (messageType !== "passport_link" ||
        (resolvedPassportIntro && resolvedPassportLink)),
  );
  const bulkDraftKey = JSON.stringify({ messageType, bulkRecipientIds, messageContent, passportIntro, headerImageId, headerImageRevision, selectedSupportContactIds });
  const canRecoverBulkRequest = bulkMode && bulkRecovery?.draftKey === bulkDraftKey;
  const submitPayload = async (payload: MessagePreviewSendPayload) => {
    if (isSending || sendInFlightRef.current) return;
    sendInFlightRef.current = true;
    setSubmissionStartedAt(Date.now());
    setError(null);
    try {
      await onSend(payload);
      setBulkRecovery(null);
    } catch (sendError) {
      if (bulkMode) setBulkRecovery({ draftKey: bulkDraftKey, payload });
      setError(readErrorMessage(sendError, "WhatsApp could not submit this broadcast."));
    } finally {
      sendInFlightRef.current = false;
      setSubmissionStartedAt(null);
    }
  };

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSend || isSending || sendInFlightRef.current) {
      if (!reminderAudienceSelectionReady) {
        setError(
          "Choose the linked passport group used to check submission status before sending.",
        );
      } else if (!reminderAudienceConfirmed) {
        setError(
          "The server did not confirm the not-submitted audience. Refresh after the dashboard update is active.",
        );
      } else if (!previewIsCurrent) {
        setError("Wait for a current message preview before sending.");
      }
      return;
    }
    setError(null);
    if (!resolvedMessageContent) {
      setError(
        "Add text before sending. Meta requires this editable template section to contain text.",
      );
      return;
    }
    if (!reminderAudienceSelectionReady) {
      setError(
        "Choose the linked passport group used to check submission status before sending.",
      );
      return;
    }
    if (!reminderAudienceConfirmed) {
      setError("The server did not confirm the not-submitted audience. Refresh after the dashboard update is active.");
      return;
    }
    if (messageType !== "reminder" && !hasHeaderImage) {
      setError(
        `Upload the required ${messageType === "welcome" ? "Welcome" : "Passport Link"} image before sending.`,
      );
      return;
    }
    if (messageType === "passport_link" && !resolvedPassportIntro) {
      setError("Add the passport introduction before sending.");
      return;
    }
    if (messageType === "passport_link" && !resolvedPassportLink) {
      setError("Paste the passport upload link before sending.");
      return;
    }
    if (
      messageType === "passport_link" &&
      !(bulkMode && selectedSupportContactIds === null) &&
      resolvedSupportContactIds.length === 0
    ) {
      setError(
        "Select at least one support contact for this Passport Link message.",
      );
      return;
    }
    if (
      messageType === "passport_link" &&
      !targetRecipient &&
      !bulkMode &&
      recipientSelectionMode === "custom" &&
      selectedRecipientIds.length === 0
    ) {
      setError("Select at least one unsent recipient for this custom send.");
      return;
    }
      await submitPayload({
        passportIntro: resolvedPassportIntro,
        passportLink: resolvedPassportLink,
        messageContent: resolvedMessageContent,
        headerImage,
        headerImageId,
        recipientIds:
          messageType === "passport_link" &&
          !targetRecipient &&
          recipientSelectionMode === "custom"
            ? selectedRecipientIds
            : null,
        supportContactIds:
          messageType === "passport_link" ? resolvedSupportContactIds : null,
        ...(messageType === "reminder" ? {
          reminderAudience,
          reminderAudienceClientGroupId: resolvedReminderAudienceClientGroupId,
        } : {}),
        ...(bulkMode ? {
          recipientIds: bulkRecipientIds,
          bulkDraft: {
            messageContent: messageContent === null ? null : resolvedMessageContent,
            passportIntro: messageType === "passport_link" && passportIntro !== null ? resolvedPassportIntro : null,
            headerImageId,
            supportContactIds: messageType === "passport_link" ? selectedSupportContactIds : null,
          },
        } : {}),
      });
  };

  return (
    <DialogFrame
      title={`${bulkMode ? "Resend" : targetRecipient ? (targetRecipient.action === "retry" ? "Retry" : "Resend") : messageType === "reminder" ? "Edit" : "Preview"} ${
        messageType === "welcome"
          ? "Welcome Message"
          : messageType === "reminder"
            ? "Reminder"
            : "Passport Link Message"
      }`}
      onClose={onClose}
      isBusy={submissionPending}
      widthClass="max-w-6xl"
      layout="composer"
      eyebrow="WhatsApp communications"
      description={group.name}
    >
      <form className="flex min-h-0 flex-1 flex-col" onSubmit={handleSend}>
        <div className="min-h-0 overflow-y-auto overscroll-contain bg-slate-50/70 px-4 py-5 sm:px-7 sm:py-6">
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-5">
        <MessageComposerSection title="Message content" description={messageType === "reminder" ? "Review and edit the reminder your recipients will receive." : "Prepare the image and wording your recipients will receive."}>
        <div className="flex gap-2.5 rounded-lg bg-blue-50/70 px-3 py-3 text-xs leading-5 text-slate-600">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          {bulkMode ? (
            <p>Edit the image and wording for the selected recipients. Fields you leave unchanged keep each person’s saved message{messageType === "passport_link" ? " and personal passport link" : ""}.</p>
          ) : messageType === "welcome" ? (
            <p>
              Add a header image and edit the message below. The greeting and
              remaining text are fixed in the approved template.
            </p>
          ) : messageType === "reminder" ? (
            <p>
              Edit the reminder paragraph below. The header, greeting, and
              sign-off are fixed in the approved template.
              {" "}Each send is a new reminder. Choose everyone or only people
              who have not submitted, then review this editor before sending.
            </p>
          ) : (
            <p>
              Add a header image, introduction, passport upload link, and
              instructions. The remaining text is fixed in the approved template.
            </p>
          )}
        </div>

        {preview?.content_source !== undefined &&
          preview.content_source !== "default" && (
            <div
              role="status"
              className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
            >
              {bulkMode
                ? `Showing the saved message for ${preview.recipient_name}. Your edits apply to the selected recipients; unchanged fields stay personal.`
                : preview.content_source === "latest_recipient"
                ? `Loaded the latest saved message for this recipient. You can edit it before ${targetRecipient?.action === "retry" ? "retrying" : "resending"}.`
                : messageType === "reminder"
                ? "Loaded your most recent reminder. Review or edit it, then confirm the audience for this send."
                : "Loaded the most recent message used for this broadcast. You can edit it before sending to the remaining recipients."}
            </div>
          )}

        {messageType !== "reminder" && (
          <div className="space-y-2">
            <label
              className={`flex cursor-pointer items-center gap-3 rounded-lg border border-dashed px-3 py-4 transition-colors focus-within:ring-2 focus-within:ring-blue-500 ${
                hasHeaderImage
                  ? "border-emerald-300 bg-emerald-50/30"
                  : "border-slate-300 bg-slate-50 hover:border-blue-400 hover:bg-blue-50/40"
              }`}
            >
              {headerImagePreview ? (
                <span className="relative h-14 w-16 shrink-0 overflow-hidden rounded-md border border-slate-200 bg-white">
                  <Image src={headerImagePreview} alt="Selected header thumbnail" fill unoptimized className="object-contain" />
                </span>
              ) : (
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500">
                  <Upload className="h-5 w-5" aria-hidden="true" />
                </span>
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold text-slate-900">
                  {messageType === "welcome"
                    ? "Welcome image"
                    : "Passport Link image"}{" "}
                  <span className="text-red-600">*</span>
                </span>
                <span className="mt-1 block break-words text-xs leading-5 text-slate-500">
                  {headerImage?.name ??
                    (effectiveHeaderImageId
                      ? "Previously sent image selected. Choose a file to replace it."
                      : "Upload the approved JPEG or PNG shown above the message.")}
                </span>
              </span>
              <span className="shrink-0 text-xs font-semibold text-blue-700">{hasHeaderImage ? "Replace" : "Browse"}</span>
              <input
                type="file"
                accept="image/jpeg,image/png,.jpg,.jpeg,.png"
                className="sr-only"
                required={!hasHeaderImage}
                onChange={(event) => {
                  const selected = event.currentTarget.files?.[0] ?? null;
                  event.currentTarget.value = "";
                  if (!selected) return;
                  if (!WELCOME_IMAGE_TYPES.has(selected.type)) {
                    replaceHeaderImage(null);
                    setError("Use a JPEG or PNG image for this message.");
                    return;
                  }
                  if (selected.size > MAX_WELCOME_IMAGE_BYTES) {
                    replaceHeaderImage(null);
                    setError("The message image must be 5 MB or smaller.");
                    return;
                  }
                  setError(null);
                  replaceHeaderImage(selected);
                }}
              />
            </label>
            <p className="text-xs text-slate-500">
              Required for every send. Maximum size: 5 MB.
            </p>
            {bulkMode && headerImage && <button type="button" className="text-xs font-semibold text-blue-700 hover:underline" onClick={() => { replaceHeaderImage(null); setHeaderImageId(null); }}>Use each recipient’s saved image</button>}
          </div>
        )}

        {messageType === "passport_link" && (
          <Input
            label="Passport upload link"
            hint={bulkMode ? "Preview only. Each recipient keeps their own personal passport link automatically." : "This upload link is included in each recipient's message."}
            placeholder="https://..."
            value={passportLink ?? preview?.passport_link ?? ""}
            onChange={bulkMode ? undefined : (event) => setPassportLink(event.target.value)}
            readOnly={bulkMode}
            required={!bulkMode}
          />
        )}

            {messageType === "passport_link" && (
              <div>
                <label
                  htmlFor={passportIntroId}
                  className="block text-sm font-medium text-slate-700"
                >
                  Passport link introduction
                </label>
                <div className="mt-1.5 overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
                  <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-2 py-1.5">
                    <button
                      type="button"
                      aria-label="Bold selected passport introduction text or start bold typing"
                      title="Bold"
                      className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() =>
                        applyBoldFormatting(
                          passportIntroRef.current,
                          passportIntro ?? preview?.passport_intro ?? "",
                          setPassportIntro,
                        )
                      }
                    >
                      <Bold className="h-3.5 w-3.5" aria-hidden="true" />
                      Bold
                    </button>
                    <span className="pr-1 text-[11px] tabular-nums text-slate-400">{(passportIntro ?? preview?.passport_intro ?? "").length} / 600</span>
                  </div>
                  <textarea
                    id={passportIntroId}
                    ref={passportIntroRef}
                    className="block min-h-28 w-full resize-y border-0 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none"
                    value={passportIntro ?? preview?.passport_intro ?? ""}
                    onChange={(event) => setPassportIntro(event.target.value)}
                    maxLength={600}
                  />
                </div>
                {passportIntro !== null && !resolvedPassportIntro && (
                  <span className="mt-1.5 block text-xs font-normal text-amber-700">
                    Enter an introduction.
                  </span>
                )}
                {bulkMode && passportIntro !== null && <button type="button" className="mt-2 text-xs font-semibold text-blue-700 hover:underline" onClick={() => setPassportIntro(null)}>Use each recipient’s saved introduction</button>}
              </div>
            )}
            <div>
              <label
                htmlFor={messageContentId}
                className="block text-sm font-medium text-slate-700"
              >
                {messageType === "welcome"
                  ? "Welcome trip message"
                  : messageType === "reminder"
                    ? "Reminder paragraph"
                    : "Passport instructions"}
              </label>
              <div className="mt-1.5 overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
                <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-2 py-1.5">
                  <button
                    type="button"
                    aria-label="Bold selected message text or start bold typing"
                    title="Bold"
                    className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() =>
                      applyBoldFormatting(
                        messageContentRef.current,
                        messageContent ?? preview?.message_content ?? "",
                        setMessageContent,
                      )
                    }
                  >
                    <Bold className="h-3.5 w-3.5" aria-hidden="true" />
                    Bold
                  </button>
                  <span className="pr-1 text-[11px] tabular-nums text-slate-400">{(messageContent ?? preview?.message_content ?? "").length} / 600</span>
                </div>
                <textarea
                  id={messageContentId}
                  ref={messageContentRef}
                  className="block min-h-40 w-full resize-y border-0 bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none"
                  value={messageContent ?? preview?.message_content ?? ""}
                  onChange={(event) => setMessageContent(event.target.value)}
                  maxLength={600}
                />
              </div>
              {messageContent !== null && !resolvedMessageContent && (
                <span className="mt-1.5 block text-xs font-normal text-amber-700">
                  Enter the message text before sending.
                </span>
              )}
              {bulkMode && messageContent !== null && <button type="button" className="mt-2 text-xs font-semibold text-blue-700 hover:underline" onClick={() => setMessageContent(null)}>Use each recipient’s saved wording</button>}
            </div>
        </MessageComposerSection>
        <MessageComposerSection title="Delivery settings" description="Confirm who will receive this message.">
          {messageType === "reminder" && !targetRecipient && !bulkMode && (
            <ReminderAudienceSelector
              audience={reminderAudience}
              audienceClientGroupId={resolvedReminderAudienceClientGroupId}
              linkedClientGroups={linkedClientGroups}
              eligibleRecipientCount={eligibleRecipientCount}
              audienceRecipientCount={audienceRecipientCount}
              excludedSubmittedCount={excludedSubmittedCount}
              excludedNeedsReviewCount={excludedNeedsReviewCount}
              isLoadingGroups={isLoadingDetail}
              isPreviewCurrent={previewIsCurrent}
              disabled={submissionPending}
              onAudienceChange={(audience) => {
                setReminderAudience(audience);
                setReminderAudienceClientGroupId(
                  audience === "not_submitted" && linkedClientGroups.length === 1
                    ? linkedClientGroups[0]?.id ?? null
                    : null,
                );
                setPreviewRecipientId(null);
                setError(null);
              }}
              onClientGroupChange={(clientGroupId) => {
                setReminderAudienceClientGroupId(clientGroupId || null);
                setPreviewRecipientId(null);
                setError(null);
              }}
            />
          )}
          {bulkRecipients && messageType !== "reminder" ? <RecipientBulkComposerAudience recipients={bulkRecipients} messageType={messageType} hiddenCount={hiddenSelectedCount} preview={bulkPreview} /> : <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500"><UsersRound className="h-5 w-5" aria-hidden="true" /></span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">
                {usesNotSubmittedAudience && !previewIsCurrent
                  ? reminderAudienceSelectionReady
                    ? "Checking eligible recipients…"
                    : "Choose a passport upload group"
                  : `${eligibleRecipientCount} eligible recipient${eligibleRecipientCount === 1 ? "" : "s"}`}
              </p>
              <p className="mt-0.5 text-xs leading-5 text-slate-500">
                {usesNotSubmittedAudience && !previewIsCurrent
                  ? "Server-confirmed counts will appear after the current submission check."
                  : usesNotSubmittedAudience
                  ? `${audienceRecipientCount ?? 0} confirmed not submitted. ${excludedSubmittedCount} submitted and ${excludedNeedsReviewCount} needing review excluded.`
                  : messageType === "reminder"
                    ? "Everyone in this audience receives an individual WhatsApp reminder, including people who received earlier reminders."
                    : "Each recipient receives an individual WhatsApp message."}
              </p>
            </div>
          </div>}
            {messageType === "passport_link" && detail && !targetRecipient && !bulkMode && (
              <fieldset className="min-w-0 rounded-lg border border-slate-200 p-3">
                <legend className="px-1 text-sm font-medium text-slate-700">
                  Recipients for this send
                </legend>
                <div className="mt-1 flex flex-wrap gap-4 text-sm text-slate-700">
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="recipient-selection-mode"
                      checked={recipientSelectionMode === "all"}
                      onChange={() => setRecipientSelectionMode("all")}
                    />
                    All unsent recipients
                  </label>
                  <label className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="recipient-selection-mode"
                      checked={recipientSelectionMode === "custom"}
                      onChange={() => {
                        const firstEligibleId = eligibleRecipients[0]?.id;
                        setRecipientSelectionMode("custom");
                        setSelectedRecipientIds((current) =>
                          current.length > 0
                            ? current
                            : firstEligibleId
                              ? [firstEligibleId]
                              : [],
                        );
                        if (firstEligibleId)
                          setPreviewRecipientId(firstEligibleId);
                      }}
                    />
                    Custom select
                  </label>
                </div>
                {recipientSelectionMode === "custom" && (
                  <details
                    className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"
                    open
                  >
                    <summary className="cursor-pointer text-sm font-semibold text-slate-800">
                      {selectedEligibleRecipients.length} recipient
                      {selectedEligibleRecipients.length === 1 ? "" : "s"}{" "}
                      selected
                    </summary>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="text-xs font-semibold text-blue-700 hover:text-blue-800"
                        onClick={() => {
                          const ids = Array.from(
                            new Set([
                              ...selectedRecipientIds,
                              ...eligibleRecipients
                                .filter((recipient) =>
                                  `${recipient.name} ${recipient.normalized_phone_number}`
                                    .toLowerCase()
                                    .includes(
                                      recipientSearch.trim().toLowerCase(),
                                    ),
                                )
                                .map((recipient) => recipient.id),
                            ]),
                          );
                          setSelectedRecipientIds(ids);
                          setPreviewRecipientId(ids[0] ?? null);
                        }}
                      >
                        Select matching
                      </button>
                      <button
                        type="button"
                        className="text-xs font-semibold text-slate-600 hover:text-slate-800"
                        onClick={() => {
                          setSelectedRecipientIds([]);
                          setPreviewRecipientId(null);
                        }}
                      >
                        Clear
                      </button>
                    </div>
                    <Input
                      type="search"
                      label="Search recipients by name or phone"
                      value={recipientSearch}
                      onChange={(event) =>
                        setRecipientSearch(event.target.value)
                      }
                      placeholder="Name or phone number"
                      className="mt-3"
                    />
                    <p className="mt-2 text-xs text-slate-500">
                      Selections stay selected when you search. Clear removes
                      all selections.
                    </p>
                    <div className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-1">
                      {eligibleRecipients
                        .filter((recipient) =>
                          `${recipient.name} ${recipient.normalized_phone_number}`
                            .toLowerCase()
                            .includes(recipientSearch.trim().toLowerCase()),
                        )
                        .map((recipient) => (
                          <label
                            key={recipient.id}
                            className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-white"
                          >
                            <input
                              type="checkbox"
                              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                              checked={selectedRecipientIdSet.has(recipient.id)}
                              onChange={(event) => {
                                const checked = event.target.checked;
                                const nextIds = checked
                                  ? Array.from(
                                      new Set([
                                        ...selectedRecipientIds,
                                        recipient.id,
                                      ]),
                                    )
                                  : selectedRecipientIds.filter(
                                      (id) => id !== recipient.id,
                                    );
                                setSelectedRecipientIds(nextIds);
                                if (checked) {
                                  setPreviewRecipientId(recipient.id);
                                } else if (
                                  previewRecipientId === recipient.id
                                ) {
                                  setPreviewRecipientId(nextIds[0] ?? null);
                                }
                              }}
                            />
                            <span className="min-w-0">
                              <span className="block break-words font-medium text-slate-800">
                                {recipient.name || "Unnamed recipient"}
                              </span>
                              <span className="block break-all text-xs text-slate-500">
                                {recipient.normalized_phone_number}
                              </span>
                            </span>
                          </label>
                        ))}
                    </div>
                  </details>
                )}
              </fieldset>
            )}
            {messageType === "passport_link" && detail && (
              <details className="rounded-xl border border-slate-200 p-3" open>
                <summary className="cursor-pointer text-sm font-medium text-slate-700">
                  {bulkMode && selectedSupportContactIds === null ? "Support contacts · keep saved details" : `Support contacts included (${resolvedSupportContactIds.length})`}
                </summary>
                <p className="mt-1 text-xs text-slate-500">
                  {bulkMode ? "Keep each person’s saved support details, or choose one contact for all selected recipients." : "Select one contact to show in this Passport Link message."}
                </p>
                <div className="mt-2 space-y-1">
                  {bulkMode && <label className="mb-2 flex items-start gap-2 rounded-md border border-blue-100 bg-blue-50/40 px-2 py-2.5 text-sm"><input type="radio" name="passport-link-support-contact" className="mt-0.5 h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500" checked={selectedSupportContactIds === null} onChange={() => setSelectedSupportContactIds(null)} /><span className="font-medium text-slate-800">Keep each recipient’s saved support details</span></label>}
                  {detail.support_contacts.map((contact) => (
                    <label
                      key={contact.id}
                      className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-slate-50"
                    >
                      <input
                        type="radio"
                        name="passport-link-support-contact"
                        className="mt-0.5 h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500"
                        checked={bulkMode ? Boolean(selectedSupportContactIds?.includes(contact.id)) : resolvedSupportContactIds.includes(contact.id)}
                        onChange={() =>
                          setSelectedSupportContactIds([contact.id])
                        }
                      />
                      <span>
                        <span className="font-medium text-slate-800">
                          {contact.name}
                        </span>
                        <span className="block text-xs text-slate-500">
                          {contact.normalized_phone_number}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </details>
            )}
            {targetRecipient && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                {targetRecipient.action === "retry" ? "Retry" : "Resend"} only
                to <strong>{targetRecipient.recipientName}</strong> (
                {targetRecipient.phoneNumber}). No other recipient will receive
                this {targetRecipient.action}.
              </div>
            )}
        </MessageComposerSection>
        </div>
        <aside aria-label="WhatsApp message preview" className="min-w-0 space-y-3 lg:sticky lg:top-0">
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <h3 className="text-sm font-semibold text-slate-900">
              {bulkMode ? "Selected recipient preview" : targetRecipient ? `One-person WhatsApp ${targetRecipient.action} preview` : "Individual WhatsApp preview"}
            </h3>
            <span className="text-xs tabular-nums text-slate-500">
              {bulkMode
                ? `${bulkRecipients?.length ?? 0} selected recipients`
                : targetRecipient
                  ? "1 selected recipient"
                  : usesNotSubmittedAudience && !previewIsCurrent
                    ? "Checking not-submitted audience…"
                    : usesNotSubmittedAudience
                    ? `${eligibleRecipientCount} ready of ${audienceRecipientCount ?? 0} not submitted`
                    : `${eligibleRecipientCount} eligible of ${preview?.recipient_count ?? group.recipient_count}`}
            </span>
          </div>
          <MessageDeliveryPreview preview={preview} previewIsCurrent={previewIsCurrent} previewFailed={Boolean(error)} messageType={messageType} headerImagePreview={headerImagePreview} headerImageId={effectiveHeaderImageId}>
            {detail &&
              (bulkMode
                ? (bulkPreview?.eligible_recipient_ids.length ?? 0) > 1
                : detail.recipients.length > 1) &&
              !targetRecipient &&
              !(messageType === "reminder" && reminderAudience === "not_submitted") && (
              <label className="block text-sm font-medium text-slate-700">
                Preview recipient
                <select
                  className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  value={previewRecipientId ?? preview?.recipient_id ?? ""}
                  onChange={(event) =>
                    setPreviewRecipientId(event.target.value)
                  }
                >
                  {(bulkMode
                    ? (bulkRecipients ?? []).filter((recipient) => bulkPreview?.eligible_recipient_ids.includes(recipient.id))
                    : recipientSelectionMode === "custom"
                    ? selectedEligibleRecipients
                    : detail.recipients
                  ).map((recipient) => (
                    <option key={recipient.id} value={recipient.id}>
                      {recipient.name || "Guest"} -{" "}
                      {recipient.normalized_phone_number}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </MessageDeliveryPreview>
            {preview && (
              <div className="mt-2 space-y-1 text-xs text-slate-500">
                {!targetRecipient && !bulkMode && messageType !== "reminder" && preview.already_sent_count > 0 && (
                  <p className="font-medium text-emerald-700">
                    {preview.already_sent_count} previous recipient
                    {preview.already_sent_count === 1 ? "" : "s"} will be
                    skipped automatically.
                  </p>
                )}
                {!targetRecipient && !bulkMode && preview.in_progress_count > 0 && (
                  <p className="font-medium text-blue-700">
                    {preview.in_progress_count} recipient
                    {preview.in_progress_count === 1 ? " is" : "s are"} already
                    queued and will not be queued twice.
                  </p>
                )}
                {!targetRecipient && !bulkMode && messageType !== "reminder" && preview.uncertain_recipient_count > 0 && (
                  <p className="font-medium text-amber-700">
                    {preview.uncertain_recipient_count} recipient
                    {preview.uncertain_recipient_count === 1
                      ? " has"
                      : "s have"}{" "}
                    an unknown delivery outcome and require review.
                  </p>
                )}
              </div>
            )}
        </aside>
        </div>
        <div className="mt-5 space-y-3">
        {isLoadingDetail && (
          <p className="text-sm text-slate-500">
            Loading recipient
            {messageType === "passport_link" ? " and support" : ""} details...
          </p>
        )}
        {detail && !detail.recipient_opt_in_confirmed && (
          <ErrorBanner message="This older list has no recorded recipient opt-in confirmation. Create a new list before sending." />
        )}
        {messageType === "passport_link" &&
          !bulkMode &&
          detail &&
          detail.support_contacts.length === 0 && (
            <ErrorBanner message="This older list has no customer support contacts. Create a new list before sending." />
          )}
        {targetRecipient && detail && !canResendTarget && (
          <ErrorBanner
            message={`This ${targetRecipient.action} can no longer be submitted because its latest delivery state changed. Refresh the recipient list before trying again.`}
          />
        )}
        {welcomeGateReason && <ErrorBanner message={welcomeGateReason} />}
        {!targetRecipient &&
          !bulkMode &&
          messageType !== "reminder" &&
          preview &&
          eligibleRecipientCount === 0 &&
          preview.already_sent_count === preview.recipient_count && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
              This message has already been sent successfully to every recipient
              in this broadcast. No duplicate messages will be sent.
            </div>
          )}
        {!targetRecipient &&
          !bulkMode &&
          messageType !== "reminder" &&
          preview &&
          eligibleRecipientCount === 0 &&
          preview.uncertain_recipient_count > 0 && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              No new deliveries can be queued.{" "}
              {preview.uncertain_recipient_count} outcome
              {preview.uncertain_recipient_count === 1 ? " is" : "s are"}{" "}
              unknown and suppressed to prevent accidental duplicate messages.
              Review these recipients before taking manual action.
            </div>
          )}
        {!targetRecipient &&
          !bulkMode &&
          preview &&
          eligibleRecipientCount === 0 &&
          preview.uncertain_recipient_count === 0 &&
          preview.in_progress_count > 0 && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
              {messageType === "reminder" ? (
                <>A reminder is still being sent to {preview.in_progress_count} recipient{preview.in_progress_count === 1 ? "" : "s"}. Wait for it to finish, then open Send Reminder again to review and send your next message.</>
              ) : <>No new deliveries can be queued: {preview.already_sent_count}{" "}
              already sent and {preview.in_progress_count} currently in
              progress.</>}
            </div>
          )}
        {!previewIsCurrent && !error && reminderAudienceSelectionReady && (
          <p role="status" className="text-sm text-slate-500">
            Updating message preview. Sending will be available after this
            version has been checked.
          </p>
        )}
        {error && <ErrorBanner message={error} />}
        {canRecoverBulkRequest && <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">The last resend has not been confirmed. Check that same request safely, even if recipient statuses have changed. Editing the message starts a different request.</p>}
        {error && !previewIsCurrent && (
          <Button
            type="button"
            variant="secondary"
            onClick={() => {
              setError(null);
              setPreviewRetryAttempt((attempt) => attempt + 1);
            }}
          >
            Retry preview
          </Button>
        )}

        </div>
        </div>
        <div data-testid="whatsapp-composer-footer" className="flex shrink-0 flex-col gap-3 border-t border-slate-200 bg-white px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <div className="flex min-w-0 items-center gap-2 text-xs text-slate-500">
            {submissionPending ? (
              <div className="w-24 shrink-0 sm:w-32">
                <WhatsAppBroadcastMotion
                  messageType={messageType}
                  state="submitting"
                  startedAt={submissionStartedAt ?? undefined}
                  compact
                />
              </div>
            ) : canSend ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" /> : <Info className="h-4 w-4 shrink-0" aria-hidden="true" />}
            <span role={submissionPending ? "status" : undefined}>{submissionPending ? "Submitting your messages..." : canSend ? "Message checked and ready to send." : "Complete the required fields and review the preview before sending."}</span>
          </div>
          <div className="flex min-w-0 items-center justify-end gap-2 sm:max-w-[60%]">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={submissionPending}
            className="shrink-0"
          >
            Cancel
          </Button>
          <Button
            type={canRecoverBulkRequest ? "button" : "submit"}
            onClick={canRecoverBulkRequest && bulkRecovery ? () => void submitPayload(bulkRecovery.payload) : undefined}
            isLoading={submissionPending}
            disabled={!canRecoverBulkRequest && (!canSend || previewPending)}
            className="min-w-0"
          >
            <Send className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span className="truncate">{canRecoverBulkRequest ? "Check resend status" : bulkMode ? `Resend to ${eligibleRecipientCount} selected` : targetRecipient
              ? `${targetRecipient.action === "retry" ? "Retry" : "Resend"} to ${targetRecipient.recipientName}`
              : usesNotSubmittedAudience && !previewIsCurrent
                ? reminderAudienceSelectionReady
                  ? "Checking not-submitted audience"
                  : "Choose a passport upload group"
                : usesNotSubmittedAudience
                ? `Send to ${eligibleRecipientCount} not submitted`
                : `Send individually to ${eligibleRecipientCount}`}</span>
          </Button>
          </div>
        </div>
      </form>
    </DialogFrame>
  );
}
