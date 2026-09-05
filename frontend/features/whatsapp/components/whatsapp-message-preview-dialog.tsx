"use client";

import { Button, Input, Skeleton } from "@/components/ui";
import { Bold, Info, Send, Upload } from "lucide-react";
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
  WhatsAppMessageType,
  WhatsAppPreviewResponse,
} from "../api/whatsapp.api";
import {
  usePreviewWhatsAppMessage,
  useWhatsAppGroup,
} from "../hooks/use-whatsapp";
import { formatMessageType } from "../utils/message-types";
import {
  getMessageStatus,
  isRecipientEligible,
} from "../utils/recipient-delivery";
import {
  parseWhatsAppBoldSegments,
  toggleWhatsAppBold,
} from "../utils/whatsapp-formatting";
import {
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import type { RecipientResendTarget } from "./whatsapp-workspace.types";

const MAX_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024;
const WELCOME_IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);

export function MessagePreviewDialog({
  group,
  messageType,
  targetRecipient,
  isSending,
  onClose,
  onSend,
}: {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
  targetRecipient?: RecipientResendTarget;
  isSending: boolean;
  onClose: () => void;
  onSend: (payload: {
    passportIntro: string;
    passportLink: string;
    messageContent: string;
    headerImage: File | null;
    headerImageId: string | null;
    recipientIds: string[] | null;
    supportContactIds: string[] | null;
  }) => Promise<void>;
}) {
  const { data: detail, isLoading: isLoadingDetail } = useWhatsAppGroup(
    group.id,
  );
  const previewRequest = usePreviewWhatsAppMessage();
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
  const [selectedSupportContactIds, setSelectedSupportContactIds] = useState<
    string[] | null
  >(null);
  const [previewRetryAttempt, setPreviewRetryAttempt] = useState(0);
  const [previewedRequestKey, setPreviewedRequestKey] = useState<string | null>(
    null,
  );
  const [headerImageRevision, setHeaderImageRevision] = useState(0);
  const [preview, setPreview] = useState<WhatsAppPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const previewSequence = useRef(0);
  const sendInFlightRef = useRef(false);
  const headerImagePreviewUrlRef = useRef<string | null>(null);
  const passportIntroRef = useRef<HTMLTextAreaElement>(null);
  const messageContentRef = useRef<HTMLTextAreaElement>(null);
  const passportIntroId = useId();
  const messageContentId = useId();
  const previewMutate = previewRequest.mutate;
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
    resolvedSupportContactIds,
    resendRecipientId: targetRecipient?.recipientId ?? null,
    groupRevision: detail?.updated_at ?? null,
  });
  const previewIsCurrent = Boolean(
    preview && previewedRequestKey === previewRequestKey,
  );

  useEffect(() => {
    const sequence = ++previewSequence.current;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
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
    resolvedSupportContactIds,
    targetRecipient,
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
  const hasHeaderImage = Boolean(headerImage || headerImageId);
  const targetRecipientDetail =
    targetRecipient && detail
      ? detail.recipients.find(
          (recipient) => recipient.id === targetRecipient.recipientId,
        )
      : undefined;
  const targetMessageStatus = targetRecipientDetail
    ? getMessageStatus(targetRecipientDetail, messageType)
    : undefined;
  const canResendTarget =
    !targetRecipient ||
    Boolean(
      targetRecipient.action === "retry"
        ? targetMessageStatus?.status === "failed"
        : targetMessageStatus?.already_sent &&
            !targetMessageStatus.resend_blocked,
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
  const eligibleRecipientCount = targetRecipient
    ? 1
    : recipientSelectionMode === "custom"
      ? selectedEligibleRecipients.length
      : (preview?.eligible_recipient_count ??
        (detail ? eligibleRecipients.length : undefined) ??
        group.recipient_count);
  const canSend = Boolean(
    previewIsCurrent &&
      !previewRequest.isPending &&
      detail?.recipient_opt_in_confirmed &&
      (messageType !== "passport_link" ||
        resolvedSupportContactIds.length > 0) &&
      resolvedMessageContent &&
      eligibleRecipientCount > 0 &&
      canResendTarget &&
      (messageType === "reminder" || hasHeaderImage) &&
      (messageType !== "passport_link" ||
        (resolvedPassportIntro && resolvedPassportLink)),
  );

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSend || isSending || sendInFlightRef.current) {
      if (!previewIsCurrent)
        setError("Wait for a current message preview before sending.");
      return;
    }
    setError(null);
    if (!resolvedMessageContent) {
      setError(
        "Add text before sending. Meta requires this editable template section to contain text.",
      );
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
      recipientSelectionMode === "custom" &&
      selectedRecipientIds.length === 0
    ) {
      setError("Select at least one unsent recipient for this custom send.");
      return;
    }
    if (isSending || sendInFlightRef.current) return;
    sendInFlightRef.current = true;
    try {
      await onSend({
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
      });
    } catch (sendError) {
      setError(
        readErrorMessage(
          sendError,
          "WhatsApp could not submit this broadcast.",
        ),
      );
    } finally {
      sendInFlightRef.current = false;
    }
  };

  return (
    <DialogFrame
      title={`${targetRecipient ? (targetRecipient.action === "retry" ? "Retry" : "Resend") : "Preview"} ${
        messageType === "welcome"
          ? "Welcome Message"
          : messageType === "reminder"
            ? "Reminder"
            : "Passport Link Message"
      }`}
      onClose={onClose}
      isBusy={isSending}
      widthClass="max-w-5xl"
    >
      <form className="space-y-5" onSubmit={handleSend}>
        <div className="flex gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-blue-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          {messageType === "welcome" ? (
            <p>
              Add a header image and edit the message below. The greeting and
              remaining text are fixed in the approved template.
            </p>
          ) : messageType === "reminder" ? (
            <p>
              Edit the reminder paragraph below. The header, greeting, and
              sign-off are fixed in the approved template.
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
              {preview.content_source === "latest_recipient"
                ? `Loaded the latest saved message for this recipient. You can edit it before ${targetRecipient?.action === "retry" ? "retrying" : "resending"}.`
                : "Loaded the most recent message used for this broadcast. You can edit it before sending to the remaining recipients."}
            </div>
          )}

        {messageType !== "reminder" && (
          <div className="space-y-2">
            <label
              className={`flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-dashed px-4 py-4 ${
                hasHeaderImage
                  ? "border-emerald-300 bg-emerald-50/50"
                  : "border-blue-300 bg-blue-50/40"
              }`}
            >
              <span className="min-w-0">
                <span className="block font-medium text-slate-900">
                  {messageType === "welcome"
                    ? "Welcome image"
                    : "Passport Link image"}{" "}
                  <span className="text-red-600">*</span>
                </span>
                <span className="block truncate text-sm text-slate-500">
                  {headerImage?.name ??
                    (headerImageId
                      ? "Previously sent image selected. Choose a file to replace it."
                      : "Upload the approved JPEG or PNG shown above the message.")}
                </span>
              </span>
              <Upload className="h-5 w-5 shrink-0 text-blue-600" />
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
          </div>
        )}

        {messageType === "passport_link" && (
          <Input
            label="Passport upload link"
            hint="This upload link is included in each recipient's message."
            placeholder="https://..."
            value={passportLink ?? preview?.passport_link ?? ""}
            onChange={(event) => setPassportLink(event.target.value)}
            required
          />
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            {messageType === "passport_link" && (
              <div>
                <label
                  htmlFor={passportIntroId}
                  className="block text-sm font-medium text-slate-700"
                >
                  Passport link introduction
                </label>
                <div className="mt-1.5 overflow-hidden rounded-lg border border-slate-300 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
                  <div className="flex items-center border-b border-slate-200 bg-slate-50 px-2 py-1.5">
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
                  </div>
                  <textarea
                    id={passportIntroId}
                    ref={passportIntroRef}
                    className="min-h-32 w-full resize-y border-0 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none"
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
                <div className="flex items-center border-b border-slate-200 bg-slate-50 px-2 py-1.5">
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
                </div>
                <textarea
                  id={messageContentId}
                  ref={messageContentRef}
                  className="min-h-56 w-full resize-y border-0 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none"
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
            </div>
            {messageType === "passport_link" && detail && !targetRecipient && (
              <fieldset className="rounded-xl border border-slate-200 p-3">
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
                  Support contacts included ({resolvedSupportContactIds.length})
                </summary>
                <p className="mt-1 text-xs text-slate-500">
                  Select one contact to show in this Passport Link message.
                </p>
                <div className="mt-2 space-y-1">
                  {detail.support_contacts.map((contact) => (
                    <label
                      key={contact.id}
                      className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-slate-50"
                    >
                      <input
                        type="radio"
                        name="passport-link-support-contact"
                        className="mt-0.5 h-4 w-4 border-slate-300 text-blue-600 focus:ring-blue-500"
                        checked={resolvedSupportContactIds.includes(contact.id)}
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
            {detail && detail.recipients.length > 1 && !targetRecipient && (
              <label className="block text-sm font-medium text-slate-700">
                Preview recipient
                <select
                  className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  value={previewRecipientId ?? preview?.recipient_id ?? ""}
                  onChange={(event) =>
                    setPreviewRecipientId(event.target.value)
                  }
                >
                  {(recipientSelectionMode === "custom"
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
            {targetRecipient && (
              <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                {targetRecipient.action === "retry" ? "Retry" : "Resend"} only
                to <strong>{targetRecipient.recipientName}</strong> (
                {targetRecipient.phoneNumber}). No other recipient will receive
                this {targetRecipient.action}.
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-slate-700">
                {targetRecipient
                  ? `One-person WhatsApp ${targetRecipient.action} preview`
                  : "Individual WhatsApp preview"}
              </h3>
              <span className="text-xs text-slate-500">
                {targetRecipient
                  ? "1 selected recipient"
                  : `${eligibleRecipientCount} eligible of ${
                      preview?.recipient_count ?? group.recipient_count
                    }`}
              </span>
            </div>
            <div className="mt-1.5 min-h-96 rounded-2xl bg-[#e5ddd5] p-4 shadow-inner">
              <div className="ml-auto max-w-[94%] rounded-xl rounded-tr-sm bg-[#dcf8c6] p-3 text-sm leading-5 text-slate-900 shadow-sm">
                {headerImagePreview ? (
                  <div className="relative mb-3 aspect-[16/10] overflow-hidden rounded-lg bg-white">
                    <Image
                      src={headerImagePreview}
                      alt={`Selected ${formatMessageType(messageType)} image header`}
                      fill
                      unoptimized
                      className="object-contain"
                    />
                  </div>
                ) : headerImageId ? (
                  <div className="mb-3 flex aspect-[16/10] items-center justify-center rounded-lg border border-emerald-200 bg-white px-4 text-center text-xs font-medium text-emerald-700">
                    The image from the previous message will be reused.
                  </div>
                ) : null}
                {preview ? (
                  <p className="whitespace-pre-wrap">
                    {parseWhatsAppBoldSegments(preview.rendered_message).map(
                      (segment, index) =>
                        segment.bold ? (
                          <strong key={`${index}:${segment.text}`}>
                            {segment.text}
                          </strong>
                        ) : (
                          <span key={`${index}:${segment.text}`}>
                            {segment.text}
                          </span>
                        ),
                    )}
                  </p>
                ) : (
                  <div className="space-y-3 py-2">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-16 w-4/5" />
                  </div>
                )}
              </div>
            </div>
            {preview && (
              <div className="mt-2 space-y-1 text-xs text-slate-500">
                <p>
                  Template: {preview.template_name} - Previewing{" "}
                  {preview.recipient_name}
                </p>
                {!targetRecipient && preview.already_sent_count > 0 && (
                  <p className="font-medium text-emerald-700">
                    {preview.already_sent_count} previous recipient
                    {preview.already_sent_count === 1 ? "" : "s"} will be
                    skipped automatically.
                  </p>
                )}
                {!targetRecipient && preview.in_progress_count > 0 && (
                  <p className="font-medium text-blue-700">
                    {preview.in_progress_count} recipient
                    {preview.in_progress_count === 1 ? " is" : "s are"} already
                    queued and will not be queued twice.
                  </p>
                )}
                {!targetRecipient && preview.uncertain_recipient_count > 0 && (
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
          </div>
        </div>

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
          detail &&
          detail.support_contacts.length === 0 && (
            <ErrorBanner message="This older list has no customer support contacts. Create a new list before sending." />
          )}
        {targetRecipient && detail && !canResendTarget && (
          <ErrorBanner
            message={`This ${targetRecipient.action} can no longer be submitted because its latest delivery state changed. Refresh the recipient list before trying again.`}
          />
        )}
        {!targetRecipient &&
          preview &&
          eligibleRecipientCount === 0 &&
          preview.already_sent_count === preview.recipient_count && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
              This message has already been sent successfully to every recipient
              in this broadcast. No duplicate messages will be sent.
            </div>
          )}
        {!targetRecipient &&
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
          preview &&
          eligibleRecipientCount === 0 &&
          preview.uncertain_recipient_count === 0 &&
          preview.in_progress_count > 0 && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
              No new deliveries can be queued: {preview.already_sent_count}{" "}
              already sent and {preview.in_progress_count} currently in
              progress.
            </div>
          )}
        {!previewIsCurrent && !error && (
          <p role="status" className="text-sm text-slate-500">
            Updating message preview. Sending will be available after this
            version has been checked.
          </p>
        )}
        {error && <ErrorBanner message={error} />}
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

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isSending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            isLoading={isSending}
            disabled={!canSend || previewRequest.isPending}
          >
            <Send className="h-4 w-4" />
            {targetRecipient
              ? `${targetRecipient.action === "retry" ? "Retry" : "Resend"} to ${targetRecipient.recipientName}`
              : `Send individually to ${eligibleRecipientCount}`}
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}
