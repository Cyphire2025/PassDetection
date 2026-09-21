"use client";

import { Plus, Search, X } from "lucide-react";
import dynamic from "next/dynamic";
import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Button, ConfirmDialog, Input, Skeleton } from "@/components/ui";
import {
  ContactEditor,
  DialogFrame,
  ErrorBanner,
  type ManualContact,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import type {
  WhatsAppBroadcastGroup,
  WhatsAppBulkResendResponse,
  WhatsAppReplacedRecipient,
  WhatsAppRecipientInput,
  WhatsAppRecipient,
} from "../api/whatsapp.api";
import { whatsappApi } from "../api/whatsapp.api";
import {
  useAddWhatsAppRecipients,
  useDeleteWhatsAppRecipient,
  useResolveWhatsAppRejectedContact,
  useResendWhatsAppRecipientMessage,
  useResendWhatsAppRecipientsMessage,
  useRestoreWhatsAppReplacedRecipient,
  useUpdateWhatsAppGroup,
  useUpdateWhatsAppRecipientPhone,
  useWhatsAppGroup,
  useWhatsAppRecipientRoster,
} from "../hooks/use-whatsapp";
import {
  getMessageStatus,
} from "../utils/recipient-delivery";
import {
  countRecipientRosterItems,
  createRecipientRosterSearchIndex,
  filterRecipientRosterItems,
  searchRecipientRosterItems,
  type WhatsAppRecipientRosterTab,
} from "../utils/recipient-roster";
import {
  formatMessageType,
} from "../utils/message-types";
import { useWhatsAppActivityTracker } from "./whatsapp-activity-tracker";
import {
  ExcelRecipientImport,
  toRejectedContactInputs,
  useRecipientExcelPreview,
} from "./whatsapp-recipient-import";
import {
  RejectedRosterRows,
  ReplacedRosterRow,
  UnidentifiedRosterRow,
  type RejectedContactCorrection,
} from "./whatsapp-recipient-roster-rows";
import { ActiveRecipientRow } from "./whatsapp-active-recipient-row";
import { RecipientBulkOutcome } from "./whatsapp-recipient-bulk-outcome";
import { RecipientWorkspaceNavigation, RecipientSelectionCheckbox, type RecipientWorkspaceSection } from "./whatsapp-recipient-selection";
import { DeliveryToolbar, DeliverySelectionBar } from "./whatsapp-delivery-toolbar";
import type { RecipientResendTarget } from "./whatsapp-workspace.types";
import type { MessagePreviewSendPayload } from "./whatsapp-message-preview-dialog";
import { useWhatsAppBroadcastSourceContacts } from "../hooks/use-whatsapp-source-groups";
import { SourceRosterPanel } from "./whatsapp-source-roster-panel";

const MessagePreviewDialog = dynamic(
  () => import("./whatsapp-message-preview-dialog").then((module) => module.MessagePreviewDialog),
  { loading: () => <DialogLoadingState label="Loading message editor" /> },
);

function DialogLoadingState({ label }: { label: string }) {
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/45 p-4"
      role="status"
      aria-live="polite"
    >
      <div className="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl">
        <p className="text-sm font-medium text-slate-700">{label}</p>
        <Skeleton className="mt-4 h-40 w-full" />
      </div>
    </div>
  );
}

const ROSTER_FILTER_IDS: WhatsAppRecipientRosterTab[] = ["all", "ready", "not_sent", "sent", "failed", "in_progress", "needs_review", "shared", "rejected", "unidentified", "replaced"];

export function RecipientListDialog({
  group,
  onClose,
}: {
  group: WhatsAppBroadcastGroup;
  onClose: () => void;
}) {
  const { registerActivity } = useWhatsAppActivityTracker();
  const {
    data: detail,
    isLoading,
    error: loadError,
    refetch: refetchGroup,
  } = useWhatsAppGroup(group.id);
  const sourceContacts = useWhatsAppBroadcastSourceContacts(group.id, Boolean(detail?.linked_client_groups?.length));
  const sourceContactCount = sourceContacts.data?.sources.length
    ? sourceContacts.data.total_contacts
    : (detail?.source_contact_count ?? 0) > 0 ? detail?.source_contact_count : undefined;
  const isArchived = Boolean(group.is_archived || detail?.is_archived);
  const updateGroup = useUpdateWhatsAppGroup();
  const addRecipientsMutation = useAddWhatsAppRecipients();
  const deleteRecipient = useDeleteWhatsAppRecipient();
  const updateRecipientPhone = useUpdateWhatsAppRecipientPhone();
  const resolveRejectedContact = useResolveWhatsAppRejectedContact();
  const restoreReplacedRecipient = useRestoreWhatsAppReplacedRecipient();
  const resendRecipientMessage = useResendWhatsAppRecipientMessage();
  const bulkResend = useResendWhatsAppRecipientsMessage();
  const [selectedSection, setSection] = useState<RecipientWorkspaceSection | null>(null);
  const defaultSection = sourceContactCount === undefined ? "recipients" : "travellers";
  const section = isArchived && selectedSection === "add" ? "recipients" : selectedSection ?? defaultSection;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkMessageType, setBulkMessageType] = useState<"welcome" | "passport_link" | "group_invite" | null>(null);
  const [bulkSelectionSnapshot, setBulkSelectionSnapshot] = useState<WhatsAppRecipient[]>([]);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const [bulkOutcome, setBulkOutcome] = useState<WhatsAppBulkResendResponse | null>(null);
  const bulkRequestRef = useRef<{ key: string; requestId: string } | null>(null);
  const bulkInFlightRef = useRef(false);
  const bulkImageUploadRef = useRef<{ file: File; mediaId: string } | null>(null);
  const [name, setName] = useState(group.name);
  const [support, setSupport] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [supportContacts, setSupportContacts] = useState<ManualContact[]>([]);
  const [manual, setManual] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [recipientRosterTab, setRecipientRosterTab] =
    useState<WhatsAppRecipientRosterTab>("all");
  const [recipientSearchQuery, setRecipientSearchQuery] = useState("");
  const [selectedMessageType, setSelectedMessageType] = useState("welcome");
  const deferredRecipientSearchQuery = useDeferredValue(recipientSearchQuery);
  const [rejectedContactEdit, setRejectedContactEdit] =
    useState<RejectedContactCorrection | null>(null);
  const [rejectedContactError, setRejectedContactError] = useState<
    string | null
  >(null);
  const [restoreReplacedError, setRestoreReplacedError] = useState<
    string | null
  >(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [recipientError, setRecipientError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [resendError, setResendError] = useState<string | null>(null);
  const [resendNotice, setResendNotice] = useState<string | null>(null);
  const [lastResendTarget, setLastResendTarget] =
    useState<RecipientResendTarget | null>(null);
  const [recipientToResend, setRecipientToResend] =
    useState<RecipientResendTarget | null>(null);
  const [recipientToRemove, setRecipientToRemove] = useState<
    (WhatsAppRecipientInput & { id: string }) | null
  >(null);
  const [replacedRecipientToRestore, setReplacedRecipientToRestore] =
    useState<WhatsAppReplacedRecipient | null>(null);
  const [editingRecipientId, setEditingRecipientId] = useState<string | null>(
    null,
  );
  const [editedPhoneNumber, setEditedPhoneNumber] = useState("");
  const initializedGroupRef = useRef<string | null>(null);
  const detailsInFlightRef = useRef(false);
  const recipientsInFlightRef = useRef(false);
  const resendInFlightRef = useRef(false);
  const {
    importState,
    previewFile,
    rejectedContacts,
    importedFieldKeys,
    resetImport,
  } = useRecipientExcelPreview({
    contacts,
    setContacts,
    excludedPhoneNumbers:
      detail?.recipients.map((recipient) => recipient.normalized_phone_number) ??
      [],
    onStart: () => {
      setRecipientError(null);
      setSuccessMessage(null);
    },
  });
  const {
    data: recipientRoster,
    isLoading: recipientRosterLoading,
    isFetching: recipientRosterFetching,
    error: recipientRosterError,
    refetch: refetchRecipientRoster,
  } = useWhatsAppRecipientRoster(group.id);

  useEffect(() => {
    if (!detail || initializedGroupRef.current === detail.id) return;
    initializedGroupRef.current = detail.id;
    setName(detail.name);
    setSupportContacts(
      detail.support_contacts.map((contact) => ({
        name: contact.name,
        phone_number: contact.phone_number,
      })),
    );
  }, [detail]);

  const addManualContact = () => {
    setRecipientError(null);
    if (!manual.name.trim() || !manual.phone_number.trim()) {
      setRecipientError("Enter both the recipient name and WhatsApp number.");
      return;
    }
    setContacts((current) => [
      ...current,
      { name: manual.name.trim(), phone_number: manual.phone_number.trim() },
    ]);
    setManual({ name: "", phone_number: "" });
  };

  const saveDetails = async () => {
    if (isArchived) return;
    setDetailsError(null);
    setSuccessMessage(null);
    if (!name.trim()) {
      setDetailsError("Enter the group name.");
      return;
    }
    if (supportContacts.length === 0) {
      setDetailsError("Keep at least one customer support contact.");
      return;
    }
    if (updateGroup.isPending || detailsInFlightRef.current) return;
    detailsInFlightRef.current = true;
    try {
      const updated = await updateGroup.mutateAsync({
        groupId: group.id,
        name: name.trim(),
        supportContacts,
      });
      setName(updated.name);
      setSupportContacts(
        updated.support_contacts.map((contact) => ({
          name: contact.name,
          phone_number: contact.phone_number,
        })),
      );
      setSuccessMessage("Broadcast details updated.");
    } catch (updateError) {
      setDetailsError(
        readErrorMessage(
          updateError,
          "Could not update the broadcast details.",
        ),
      );
    } finally {
      detailsInFlightRef.current = false;
    }
  };

  const addRecipients = async () => {
    if (isArchived) return;
    setRecipientError(null);
    setSuccessMessage(null);
    if (importState.status === "loading") {
      setRecipientError("Wait for the Excel contacts to finish loading.");
      return;
    }
    if (contacts.length === 0 && rejectedContacts.length === 0) {
      setRecipientError(
        "Add at least one named recipient or import rejected rows for correction.",
      );
      return;
    }
    if (
      contacts.some(
        (contact) => !contact.name.trim() || !contact.phone_number.trim(),
      )
    ) {
      setRecipientError(
        "Every new recipient needs both a name and WhatsApp number.",
      );
      return;
    }
    if (contacts.length > 0 && !recipientOptInConfirmed) {
      setRecipientError(
        "Confirm that the new recipients agreed to receive WhatsApp updates.",
      );
      return;
    }
    if (
      addRecipientsMutation.isPending
      || recipientsInFlightRef.current
    ) return;
    recipientsInFlightRef.current = true;
    try {
      const updated = await addRecipientsMutation.mutateAsync({
        groupId: group.id,
        contacts,
        rejectedContacts: toRejectedContactInputs(rejectedContacts),
        recipientOptInConfirmed:
          contacts.length > 0 && recipientOptInConfirmed,
        importedFieldKeys,
      });
      const savedRejectedCount = rejectedContacts.length;
      setContacts([]);
      resetImport();
      setRecipientOptInConfirmed(false);
      setRecipientRosterTab("all");
      setSection("recipients");
      setSuccessMessage(
        `Recipient list updated. It now contains ${updated.recipient_count} valid recipient${updated.recipient_count === 1 ? "" : "s"}.${savedRejectedCount > 0 ? ` ${savedRejectedCount} rejected contact${savedRejectedCount === 1 ? " was" : "s were"} saved for correction.` : ""}`,
      );
    } catch (updateError) {
      setRecipientError(
        readErrorMessage(updateError, "Could not add these recipients."),
      );
    } finally {
      recipientsInFlightRef.current = false;
    }
  };

  const resendSelectedMessage = async (payload: MessagePreviewSendPayload) => {
    if (
      !recipientToResend
      || isArchived
      || resendRecipientMessage.isPending
      || resendInFlightRef.current
    ) return;

    const target = recipientToResend;
    const startedAt = Date.now();
    resendInFlightRef.current = true;
    setResendError(null);
    setResendNotice(null);
    setLastResendTarget(null);
    try {
      const result = await resendRecipientMessage.mutateAsync({
        groupId: group.id,
        recipientId: target.recipientId,
        messageType: target.messageType,
        passportIntro: payload.passportIntro,
        passportLink: payload.passportLink,
        groupInviteLink: payload.groupInviteLink,
        messageContent: payload.messageContent,
        image: payload.headerImage,
        headerImageId: payload.headerImageId,
        supportContactIds: payload.supportContactIds,
      });
      if (result.batch_id) {
        registerActivity({
          id: result.batch_id,
          kind: "broadcast",
          messageType: target.messageType,
          startedAt,
          title: `${formatMessageType(target.messageType)} ${target.action}`,
          contextLabel: `${target.recipientName} - ${group.name}`,
          sourceGroupId: group.id,
          documentType: null,
          total:
            result.queued
            + result.sent
            + result.failed
            + result.delivery_unknown,
          queued: result.queued,
          sent: result.sent,
          failed: result.failed,
          deliveryUnknown: result.delivery_unknown,
          skippedAlreadySent: result.skipped_already_sent,
          skippedInProgress: result.skipped_in_progress,
          skippedDeliveryUnknown: result.skipped_delivery_unknown,
        });
      }
      setRecipientToResend(null);
      setLastResendTarget(target);

      if (result.queued > 0) {
        setResendNotice(
          `${formatMessageType(target.messageType)} ${target.action} queued for ${target.recipientName} only.`,
        );
      } else if (result.sent > 0) {
        setResendNotice(
          `${formatMessageType(target.messageType)} ${target.action === "retry" ? "sent" : "resent"} to ${target.recipientName} only.`,
        );
      } else {
        setResendError(
          `${formatMessageType(target.messageType)} was not ${target.action === "retry" ? "retried" : "resent"}. Refresh the recipient status before trying again.`,
        );
      }
    } catch (resendRequestError) {
      setLastResendTarget(null);
      setResendError(
        readErrorMessage(
          resendRequestError,
          `Could not ${target.action} the ${formatMessageType(target.messageType).toLowerCase()} to ${target.recipientName}.`,
        ),
      );
      throw resendRequestError;
    } finally {
      resendInFlightRef.current = false;
    }
  };

  const messageTypes = useMemo(
    () =>
      Array.from(
        new Set([
          "welcome",
          "passport_link",
          "group_invite",
          "reminder",
          ...(recipientRoster?.items.flatMap((item) =>
            item.kind === "recipient"
              ? item.recipient.message_statuses.map(
                  (status) => status.message_type,
                )
              : [],
          ) ?? []),
        ]),
      ),
    [recipientRoster?.items],
  );
  const sourceNamesByPhone = useMemo(() => {
    const names = new Map<string, string[]>();
    for (const contact of sourceContacts.data?.contacts ?? []) {
      if (!contact.normalized_phone_number) continue;
      const entries = names.get(contact.normalized_phone_number) ?? [];
      entries.push(contact.name || "Name missing");
      names.set(contact.normalized_phone_number, entries);
    }
    return names;
  }, [sourceContacts.data?.contacts]);
  const sharedPhones = useMemo(() => new Set([...sourceNamesByPhone].filter(([, names]) => names.length > 1).map(([phone]) => phone)), [sourceNamesByPhone]);
  const hasRecipientSearch = Boolean(deferredRecipientSearchQuery.trim());
  const rosterSearchIndex = useMemo(() => hasRecipientSearch ? createRecipientRosterSearchIndex(recipientRoster?.items ?? [], sourceNamesByPhone) : undefined, [recipientRoster?.items, sourceNamesByPhone, hasRecipientSearch]);
  const searchedRosterItems = useMemo(() => searchRecipientRosterItems(recipientRoster?.items ?? [], deferredRecipientSearchQuery, sourceNamesByPhone, rosterSearchIndex), [recipientRoster?.items, deferredRecipientSearchQuery, sourceNamesByPhone, rosterSearchIndex]);
  const filterCounts = useMemo(() => Object.fromEntries(ROSTER_FILTER_IDS.map((id) => [id, countRecipientRosterItems(searchedRosterItems, id, selectedMessageType, sharedPhones)])) as Record<WhatsAppRecipientRosterTab, number>, [searchedRosterItems, selectedMessageType, sharedPhones]);
  const visibleRosterItems = useMemo(
    () => filterRecipientRosterItems(searchedRosterItems, recipientRosterTab, selectedMessageType, sharedPhones),
    [searchedRosterItems, recipientRosterTab, selectedMessageType, sharedPhones],
  );
  const allRecipients = useMemo(() => recipientRoster?.items.flatMap((item) => item.kind === "recipient" ? [item.recipient] : []) ?? [], [recipientRoster?.items]);
  const visibleRecipientIds = useMemo(() => visibleRosterItems.flatMap((item) => item.kind === "recipient" ? [item.recipient.id] : []), [visibleRosterItems]);
  const selectedRecipients = useMemo(() => allRecipients.filter((recipient) => selectedIds.has(recipient.id)), [allRecipients, selectedIds]);
  const visibleSelectedCount = visibleRecipientIds.filter((id) => selectedIds.has(id)).length;
  const allVisibleSelected = visibleRecipientIds.length > 0 && visibleSelectedCount === visibleRecipientIds.length;
  const someVisibleSelected = visibleSelectedCount > 0;
  const hiddenSelectedCount = selectedRecipients.length - visibleSelectedCount;
  const selectionLocked = isArchived || bulkResend.isPending || Boolean(bulkMessageType);
  const clearSelection = () => {
    setSelectedIds(new Set());
    bulkRequestRef.current = null;
    setBulkError(null);
    setBulkNotice(null);
  };
  const changeDeliveryFilter = (filter: WhatsAppRecipientRosterTab) => {
    setRecipientRosterTab(filter);
    setRejectedContactEdit(null);
    setRejectedContactError(null);
    setRestoreReplacedError(null);
  };
  const openBulkComposer = (type: "welcome" | "passport_link" | "group_invite") => {
    setBulkSelectionSnapshot(selectedRecipients);
    setBulkMessageType(type);
    setBulkError(null);
  };
  const toggleRecipients = (ids: string[], checked: boolean) => {
    if (selectionLocked) return;
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const id of ids) { if (checked) next.add(id); else next.delete(id); }
      return next;
    });
    bulkRequestRef.current = null;
    setBulkError(null);
    setBulkNotice(null);
  };
  const confirmBulkResend = async (payload: MessagePreviewSendPayload) => {
    if (isArchived) return;
    const recipientIds = payload.recipientIds ?? bulkSelectionSnapshot.map((recipient) => recipient.id);
    if (!bulkMessageType || bulkInFlightRef.current || bulkResend.isPending || recipientIds.length === 0) return;
    const messageType = bulkMessageType;
    bulkInFlightRef.current = true;
    setBulkError(null);
    setBulkNotice(null);
    const startedAt = Date.now();
    try {
      let uploadedImageId: string | null = null;
      if (payload.headerImage) {
        if (bulkImageUploadRef.current?.file !== payload.headerImage) {
          const image = await whatsappApi.uploadWelcomeImage(group.id, payload.headerImage);
          bulkImageUploadRef.current = { file: payload.headerImage, mediaId: image.media_id };
        }
        uploadedImageId = bulkImageUploadRef.current.mediaId;
      }
      const overrides = {
        messageContent: payload.bulkDraft?.messageContent ?? null,
        headerImageId: uploadedImageId ?? payload.bulkDraft?.headerImageId ?? null,
        ...(messageType === "group_invite" ? { groupInviteLink: payload.bulkDraft?.groupInviteLink ?? null } : {
        passportIntro: payload.bulkDraft?.passportIntro ?? null,
        supportContactIds: payload.bulkDraft?.supportContactIds ?? null,
        }),
      };
      const requestKey = JSON.stringify([group.id, messageType, [...recipientIds].sort(), overrides]);
      if (bulkRequestRef.current?.key !== requestKey) bulkRequestRef.current = { key: requestKey, requestId: crypto.randomUUID() };
      const result = await bulkResend.mutateAsync({ groupId: group.id, messageType, recipientIds, requestId: bulkRequestRef.current.requestId, overrides });
      setBulkOutcome(result);
      if (result.batch_id) registerActivity({
        id: result.batch_id, kind: "broadcast", messageType, startedAt,
        title: `${formatMessageType(messageType)} resend`, contextLabel: `${recipientIds.length} selected · ${group.name}`,
        sourceGroupId: group.id, documentType: null,
        total: result.queued + result.sent + result.failed + result.delivery_unknown,
        queued: result.queued, sent: result.sent, failed: result.failed, deliveryUnknown: result.delivery_unknown,
        skippedAlreadySent: result.skipped_already_sent, skippedInProgress: result.skipped_in_progress, skippedDeliveryUnknown: result.skipped_delivery_unknown,
      });
      const skipped = result.skipped_already_sent + result.skipped_in_progress + result.skipped_delivery_unknown + result.skipped_no_saved_message + result.skipped_replaced + result.skipped_ineligible;
      const skipReasons = [
        result.skipped_already_sent > 0 ? `${result.skipped_already_sent} already sent` : null,
        result.skipped_in_progress > 0 ? `${result.skipped_in_progress} already in progress` : null,
        result.skipped_delivery_unknown > 0 ? `${result.skipped_delivery_unknown} need delivery review` : null,
        result.skipped_no_saved_message > 0 ? `${result.skipped_no_saved_message} have no saved message` : null,
        result.skipped_replaced > 0 ? `${result.skipped_replaced} replaced` : null,
        result.skipped_ineligible > 0 ? `${result.skipped_ineligible} not eligible` : null,
      ].filter(Boolean).join("; ");
      const outcomes = [
        result.queued > 0 ? `${result.queued} queued` : null,
        result.sent > 0 ? `${result.sent} sent` : null,
        result.failed > 0 ? `${result.failed} failed` : null,
        result.delivery_unknown > 0 ? `${result.delivery_unknown} awaiting delivery review` : null,
        skipped > 0 ? `${skipped} skipped (${skipReasons})` : null,
      ].filter(Boolean).join(" · ");
      setBulkNotice(`${formatMessageType(messageType)}: ${outcomes || "no messages queued"}. Selection kept for your next action.`);
      setBulkMessageType(null);
      bulkRequestRef.current = null;
    } catch (error) {
      setBulkError(readErrorMessage(error, "Could not confirm the resend. Retry to check this same request safely."));
      throw error;
    } finally {
      bulkInFlightRef.current = false;
    }
  };

  const lastResendMessageStatus =
    lastResendTarget && detail
      ? getMessageStatus(
          detail.recipients.find(
            (recipient) => recipient.id === lastResendTarget.recipientId,
          ) ?? { message_statuses: [] },
          lastResendTarget.messageType,
        )
      : null;
  const lastResendStatus = lastResendMessageStatus?.latest_resend_status;
  const displayedResendError =
    lastResendTarget && lastResendStatus === "failed"
      ? `${formatMessageType(lastResendTarget.messageType)} could not be resent to ${lastResendTarget.recipientName}.`
      : lastResendTarget && lastResendStatus === "delivery_unknown"
        ? `${formatMessageType(lastResendTarget.messageType)} delivery to ${lastResendTarget.recipientName} is unknown. Review it before trying again.`
        : resendError;
  const displayedResendNotice =
    lastResendTarget
    && (
      lastResendStatus === "sent"
      || lastResendStatus === "delivered"
      || lastResendStatus === "read"
    )
      ? `${formatMessageType(lastResendTarget.messageType)} resent to ${lastResendTarget.recipientName} only.`
      : lastResendTarget
          && (
            lastResendStatus === "failed"
            || lastResendStatus === "delivery_unknown"
          )
        ? null
        : resendNotice;

  return (
    <>
      {((!recipientToResend && !bulkMessageType) || isArchived) && (
        <DialogFrame
          title={`Recipients — ${detail?.name ?? group.name}`}
          eyebrow="WhatsApp broadcast"
          description={isArchived ? "Archived broadcast. Review retained recipients and delivery history." : "Manage your audience, review delivery and send selected messages again."}
          layout="composer"
          onClose={onClose}
          isBusy={
            updateGroup.isPending
            || addRecipientsMutation.isPending
            || deleteRecipient.isPending
            || updateRecipientPhone.isPending
            || resolveRejectedContact.isPending
            || restoreReplacedRecipient.isPending
            || resendRecipientMessage.isPending
            || bulkResend.isPending
            || (!isArchived && Boolean(bulkMessageType))
            || (!isArchived && Boolean(recipientToRemove))
            || (!isArchived && Boolean(replacedRecipientToRestore))
          }
          widthClass="max-w-[1600px] h-[94dvh]"
        >
        <RecipientWorkspaceNavigation section={section} onChange={setSection} recipientCount={detail?.recipient_count ?? group.recipient_count} pendingCount={contacts.length + rejectedContacts.length} readOnly={isArchived} sourceContactCount={sourceContactCount} />
        <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/70 p-4 sm:p-6">
        {isArchived && <p role="status" className="mb-4 rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-700">This broadcast is archived and read-only. Restore it from Archived broadcasts to edit recipients or send messages.</p>}
        {loadError ? (
          <ErrorBanner message="The recipient list could not be loaded." />
        ) : isLoading || !detail ? (
          <div className="space-y-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-48" />
          </div>
        ) : (
          <div className="space-y-4">
            {section === "travellers" && <SourceRosterPanel data={sourceContacts.data} isLoading={sourceContacts.isLoading} isFetching={sourceContacts.isFetching} error={sourceContacts.error} onRetry={() => void sourceContacts.refetch()} />}
            {section === "details" && (
            <fieldset disabled={isArchived}>
            <section className="mx-auto w-full max-w-4xl rounded-2xl border border-slate-200 bg-white p-5 sm:p-7">
              <div>
                <h3 className="font-semibold text-slate-900">
                  Broadcast details
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  The group name is used in both approved messages. Support
                  contacts are used only in the Passport Link message.
                </p>
              </div>
              <div className="mt-4 max-w-xl">
                <Input
                  label="Group name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={100}
                />
              </div>
              <div className="mt-4">
                <ContactEditor
                  title="Passport-link support contacts"
                  description="These contacts appear only at the end of the Passport Link message. Welcome messages do not include them."
                  value={support}
                  contacts={supportContacts}
                  onValueChange={setSupport}
                  onAdd={() => {
                    setDetailsError(null);
                    if (supportContacts.length >= 3) {
                      setDetailsError(
                        "You can keep up to three customer support contacts.",
                      );
                      return;
                    }
                    if (!support.name.trim() || !support.phone_number.trim()) {
                      setDetailsError(
                        "Enter both the support contact name and WhatsApp number.",
                      );
                      return;
                    }
                    setSupportContacts((current) => [
                      ...current,
                      {
                        name: support.name.trim(),
                        phone_number: support.phone_number.trim(),
                      },
                    ]);
                    setSupport({ name: "", phone_number: "" });
                  }}
                  onRemove={(index) => {
                    if (supportContacts.length <= 1) {
                      setDetailsError(
                        "Keep at least one customer support contact.",
                      );
                      return;
                    }
                    setSupportContacts((current) =>
                      current.filter((_, itemIndex) => itemIndex !== index),
                    );
                  }}
                />
              </div>
              {detailsError && (
                <div className="mt-4">
                  <ErrorBanner message={detailsError} />
                </div>
              )}
              <div className="mt-4 flex justify-end">
                <Button
                  type="button"
                  variant="secondary"
                  isLoading={updateGroup.isPending}
                  disabled={
                    !name.trim() ||
                    supportContacts.length === 0 ||
                    (name.trim() === detail.name &&
                      JSON.stringify(supportContacts) ===
                        JSON.stringify(
                          detail.support_contacts.map((contact) => ({
                            name: contact.name,
                            phone_number: contact.phone_number,
                          })),
                        ))
                  }
                  onClick={saveDetails}
                >
                  Save Details
                </Button>
              </div>
            </section>
            </fieldset>
            )}
            {section === "add" && !isArchived && (
            <section className="mx-auto w-full max-w-4xl space-y-5 rounded-2xl border border-slate-200 bg-white p-5 sm:p-7">
              <div>
                <h3 className="font-semibold text-slate-900">Add recipients</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Add recipients manually or import an Excel file. Duplicate phone
                  numbers are skipped; invalid rows can be saved for correction.
                </p>
              </div>

              <ContactEditor
                title="Manual recipients"
                description="Names are required so staff can identify each recipient and review delivery status."
                value={manual}
                contacts={contacts}
                onValueChange={(value) => {
                  setRecipientError(null);
                  setManual(value);
                }}
                onAdd={addManualContact}
                onRemove={(index) => {
                  setRecipientError(null);
                  setContacts((current) =>
                    current.filter((_, itemIndex) => itemIndex !== index),
                  );
                }}
                onContactChange={(index, contact) => {
                  setRecipientError(null);
                  setContacts((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index ? contact : item,
                    ),
                  );
                }}
              />

              <ExcelRecipientImport
                state={importState}
                onFile={previewFile}
                label="Upload additional Excel contacts"
              />

              {contacts.length > 0 ? (
                <label className="flex items-start gap-3 rounded-xl border border-blue-100 bg-white p-4 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={recipientOptInConfirmed}
                    onChange={(event) =>
                      setRecipientOptInConfirmed(event.target.checked)
                    }
                  />
                  <span>
                    I confirm the new recipients agreed to receive trip-related
                    WhatsApp updates.
                  </span>
                </label>
              ) : rejectedContacts.length > 0 ? (
                <p className="rounded-xl border border-amber-200 bg-white p-4 text-sm text-amber-800">
                  This import has no valid recipients. You can still save its
                  rejected rows for correction; no WhatsApp messages can be
                  sent to them.
                </p>
              ) : null}

              {recipientError && <ErrorBanner message={recipientError} />}
              <div className="flex justify-end">
                <Button
                  type="button"
                  isLoading={addRecipientsMutation.isPending}
                  disabled={
                    (contacts.length === 0 &&
                      rejectedContacts.length === 0) ||
                    (contacts.length > 0 && !recipientOptInConfirmed) ||
                    importState.status === "loading"
                  }
                  onClick={addRecipients}
                >
                  <Plus className="h-4 w-4" />
                  Add Recipients
                </Button>
              </div>
            </section>
            )}
            {section === "recipients" && (
            <div className="space-y-4">
            <section className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
              {bulkOutcome && <RecipientBulkOutcome response={bulkOutcome} recipients={allRecipients} onDismiss={() => setBulkOutcome(null)} />}
              <DeliveryToolbar
                messageTypes={messageTypes}
                messageType={selectedMessageType}
                onMessageTypeChange={(type) => { setSelectedMessageType(type); clearSelection(); setBulkOutcome(null); changeDeliveryFilter("all"); }}
                filter={recipientRosterTab}
                onFilterChange={changeDeliveryFilter}
                counts={filterCounts}
                disabled={bulkResend.isPending || Boolean(bulkMessageType)}
                refreshing={recipientRosterFetching}
                onRefresh={() => { void refetchRecipientRoster(); void refetchGroup(); }}
              />

              <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
                <div className="w-full sm:max-w-xl">
                  <Input
                    id="recipient-roster-search"
                    type="search"
                    value={recipientSearchQuery}
                    onChange={(event) => setRecipientSearchQuery(event.target.value)}
                    placeholder="Search name, number, passport or imported details"
                    aria-label="Search current recipients"
                    leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
                    rightAddon={
                      recipientSearchQuery ? (
                        <button
                          type="button"
                          className="-mr-2 inline-flex h-8 w-8 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                          aria-label="Clear recipient search"
                          onClick={() => setRecipientSearchQuery("")}
                        >
                          <X className="h-4 w-4" aria-hidden="true" />
                        </button>
                      ) : null
                    }
                  />
                </div>
                <p className="shrink-0 text-xs font-medium text-slate-500" aria-live="polite">
                  {visibleRosterItems.length.toLocaleString()} matching
                  {visibleRosterItems.length === 1 ? " person" : " people"}
                </p>
              </div>

              {!isArchived && <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2.5">
                <span className="text-xs text-slate-500">{selectedRecipients.length ? `${selectedRecipients.length.toLocaleString()} selected across the broadcast` : "Choose people using the checkboxes"}</span>
                <button type="button" disabled={!visibleRecipientIds.length || selectionLocked} onClick={() => toggleRecipients(visibleRecipientIds, !allVisibleSelected)} className="text-xs font-semibold text-blue-700 hover:underline disabled:opacity-40">{allVisibleSelected ? "Deselect matching" : `Select all matching (${visibleRecipientIds.length.toLocaleString()})`}</button>
              </div>}
              <details className="mt-3 text-xs text-slate-500">
                <summary className="cursor-pointer hover:text-slate-800">About these delivery filters</summary>
                <p className="mt-2 max-w-3xl leading-relaxed">Every delivery filter uses the selected message type. Sent includes messages accepted by WhatsApp; only Delivered or Read confirms receipt. Ready includes eligible first sends and failed attempts. Needs review includes uncertain delivery or a missing required welcome. A failed later resend can appear under Failed while the original remains Sent. Shared numbers represent multiple travellers receiving one copy. Contact records lists rejected imports, replaced people and unidentified uploads separately.</p>
              </details>
              {recipientError && <div className="mt-3"><ErrorBanner message={recipientError} /></div>}
              {displayedResendError && (
                <div className="mt-3">
                  <ErrorBanner message={displayedResendError} />
                </div>
              )}
              {displayedResendNotice && (
                <div
                  className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700"
                  role="status"
                >
                  {displayedResendNotice}
                </div>
              )}
              {rejectedContactError && (
                <div className="mt-3">
                  <ErrorBanner message={rejectedContactError} />
                </div>
              )}
              {restoreReplacedError && (
                <div className="mt-3">
                  <ErrorBanner message={restoreReplacedError} />
                </div>
              )}

              <div
                id="recipient-roster-panel"
                role="region"
                aria-label="Filtered delivery numbers"
                className="mt-3"
              >
                {recipientRosterError ? (
                  <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                    <p role="alert" className="text-sm text-red-700">
                      The recipient roster could not be loaded.
                    </p>
                    <button
                      type="button"
                      className="mt-2 text-sm font-semibold text-blue-700 hover:text-blue-800"
                      onClick={() => void refetchRecipientRoster()}
                    >
                      Try again
                    </button>
                  </div>
                ) : recipientRosterLoading || !recipientRoster ? (
                  <div
                    className="space-y-2"
                    role="status"
                    aria-label="Loading recipient roster"
                  >
                    <Skeleton className="h-12" />
                    <Skeleton className="h-12" />
                    <Skeleton className="h-12" />
                  </div>
                ) : visibleRosterItems.length === 0 ? (
                  <p className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
                    {deferredRecipientSearchQuery.trim()
                      ? `No recipients match "${deferredRecipientSearchQuery.trim()}" in this filter.`
                      : recipientRosterTab === "unidentified"
                      ? "No unidentified uploads were found."
                      : `No ${recipientRosterTab === "all" ? "" : `${recipientRosterTab} `}contacts were found.`}
                  </p>
                ) : (
                  <div className="max-h-[max(260px,calc(94dvh-400px))] overflow-auto rounded-xl border border-slate-200">
                    <table className="w-full min-w-[640px] text-left text-sm">
                      <caption className="sr-only">{formatMessageType(selectedMessageType)} delivery and contact records</caption>
                      <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <tr>
                          <th scope="col" className="w-12 px-4 py-3 text-center"><RecipientSelectionCheckbox label="Select all matching recipients" checked={allVisibleSelected} indeterminate={someVisibleSelected && !allVisibleSelected} disabled={!visibleRecipientIds.length || selectionLocked} onChange={(checked) => toggleRecipients(visibleRecipientIds, checked)} /></th>
                          <th scope="col" className="w-12 px-2 py-3 text-center">#</th>
                          <th scope="col" className="px-4 py-3">Recipient</th>
                          <th scope="col" className="px-4 py-3">WhatsApp number</th>
                          <th scope="col" className="px-4 py-3">Delivery status</th>
                          <th scope="col" className="px-4 py-3 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {visibleRosterItems.map((item, index) => {
                          const serialNumber = index + 1;
                          if (item.kind === "unidentified") {
                            return (
                              <UnidentifiedRosterRow
                                key={`unidentified:${item.unidentified_upload.submission_id}`}
                                upload={item.unidentified_upload}
                                serialNumber={serialNumber}
                                messageColumnCount={1}
                                showSelectionColumn
                              />
                            );
                          }
                          if (item.kind === "replaced") {
                            const replacedRecipient = item.replaced_recipient;
                            return (
                              <ReplacedRosterRow
                                key={`replaced:${replacedRecipient.recipient_id}`}
                                recipient={replacedRecipient}
                                serialNumber={serialNumber}
                                messageColumnCount={1}
                                showSelectionColumn
                                readOnly={isArchived}
                                isRestoring={restoreReplacedRecipient.isPending}
                                onRestore={() => {
                                  setRestoreReplacedError(null);
                                  setReplacedRecipientToRestore(
                                    replacedRecipient,
                                  );
                                }}
                              />
                            );
                          }
                          if (item.kind === "rejected") {
                            const contact = item.rejected_contact;
                            return (
                              <RejectedRosterRows
                                key={`rejected:${contact.id}`}
                                contact={contact}
                                serialNumber={serialNumber}
                                messageColumnCount={1}
                                showSelectionColumn
                                readOnly={isArchived}
                                correction={isArchived ? null : rejectedContactEdit}
                                isSaving={resolveRejectedContact.isPending}
                                onEdit={() => {
                                  setRejectedContactError(null);
                                  setRejectedContactEdit({
                                    id: contact.id,
                                    name: contact.raw_name?.trim() || "",
                                    phoneNumber:
                                      contact.raw_phone_number?.trim() || "",
                                    optInConfirmed:
                                      detail.recipient_opt_in_confirmed,
                                  });
                                }}
                                onCorrectionChange={setRejectedContactEdit}
                                onCancel={() => {
                                  setRejectedContactEdit(null);
                                  setRejectedContactError(null);
                                }}
                                onSave={async () => {
                                  const correction = rejectedContactEdit;
                                  if (!correction || correction.id !== contact.id) {
                                    return;
                                  }
                                  setRejectedContactError(null);
                                  try {
                                    await resolveRejectedContact.mutateAsync({
                                      groupId: group.id,
                                      rejectedContactId: contact.id,
                                      name: correction.name.trim(),
                                      phoneNumber:
                                        correction.phoneNumber.trim(),
                                      recipientOptInConfirmed:
                                        correction.optInConfirmed,
                                    });
                                    setRejectedContactEdit(null);
                                    setSuccessMessage(
                                      `${correction.name.trim()} was added to the valid recipient list as Not sent.`,
                                    );
                                  } catch (correctionError) {
                                    setRejectedContactError(
                                      readErrorMessage(
                                        correctionError,
                                        "Could not add this corrected contact.",
                                      ),
                                    );
                                  }
                                }}
                              />
                            );
                          }

                          const recipient = item.recipient;
                          return (
                            <ActiveRecipientRow
                              key={`recipient:${recipient.id}`}
                              recipient={recipient}
                              serialNumber={serialNumber}
                              messageTypes={[selectedMessageType]}
                              sharedContactNames={sourceNamesByPhone.get(recipient.normalized_phone_number)}
                              selected={selectedIds.has(recipient.id)}
                              selectionDisabled={selectionLocked}
                              onSelect={(checked) => toggleRecipients([recipient.id], checked)}
                              editing={!isArchived && editingRecipientId === recipient.id}
                              editedPhone={editedPhoneNumber}
                              onPhoneChange={setEditedPhoneNumber}
                              onEdit={() => {
                                setRecipientError(null);
                                setEditingRecipientId(recipient.id);
                                setEditedPhoneNumber(recipient.phone_number);
                              }}
                              onCancelEdit={() => setEditingRecipientId(null)}
                              phoneSaving={updateRecipientPhone.isPending}
                              onSavePhone={async () => {
                                setRecipientError(null);
                                try {
                                  await updateRecipientPhone.mutateAsync({ groupId: group.id, recipientId: recipient.id, phoneNumber: editedPhoneNumber.trim() });
                                  setEditingRecipientId(null);
                                  setSuccessMessage(`WhatsApp number updated for ${recipient.name || "this recipient"}. Previous message statuses are ready to retry on the new number.`);
                                } catch (phoneError) {
                                  setRecipientError(readErrorMessage(phoneError, "Could not update this WhatsApp number."));
                                }
                              }}
                              resendPending={resendRecipientMessage.isPending}
                              onResend={(target) => {
                                setResendError(null);
                                setResendNotice(null);
                                setLastResendTarget(null);
                                setRecipientToResend(target);
                              }}
                              removeDisabled={detail.recipient_count <= 1 || deleteRecipient.isPending}
                              onRemove={() => setRecipientToRemove({ id: recipient.id, name: recipient.name, phone_number: recipient.phone_number })}
                            />
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>

            </div>
            )}

            {section === "recipients" && bulkNotice && <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{bulkNotice}</p>}
            {section === "recipients" && bulkError && !bulkMessageType && <div><ErrorBanner message={bulkError} /></div>}
            {successMessage && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
                {successMessage}
              </div>
            )}
          </div>
        )}
        </div>
        {section === "recipients" && !isArchived && <DeliverySelectionBar selectedCount={selectedRecipients.length} hiddenCount={hiddenSelectedCount} messageType={selectedMessageType} onClear={clearSelection} onReview={openBulkComposer} disabled={selectionLocked} />}
        </DialogFrame>
      )}

      {recipientToResend && !isArchived && (
        <MessagePreviewDialog
          group={group}
          messageType={recipientToResend.messageType}
          targetRecipient={recipientToResend}
          isSending={resendRecipientMessage.isPending}
          onClose={() => {
            if (
              !resendRecipientMessage.isPending
              && !resendInFlightRef.current
            ) {
              setRecipientToResend(null);
            }
          }}
          onSend={resendSelectedMessage}
        />
      )}

      {bulkMessageType && !isArchived && <MessagePreviewDialog group={group} messageType={bulkMessageType} bulkRecipients={bulkSelectionSnapshot} hiddenSelectedCount={hiddenSelectedCount} isSending={bulkResend.isPending} onClose={() => { if (!bulkResend.isPending && !bulkInFlightRef.current) setBulkMessageType(null); }} onSend={confirmBulkResend} />}

      <ConfirmDialog
        isOpen={!isArchived && Boolean(replacedRecipientToRestore)}
        title="Restore the original recipient?"
        description={`${replacedRecipientToRestore?.name || replacedRecipientToRestore?.normalized_phone_number || "This recipient"} will become active for future WhatsApp messages again. ${replacedRecipientToRestore?.replacement_name || "The replacement upload"} will return to Unidentified uploads in ${replacedRecipientToRestore?.client_group_name || "the passport group"}.`}
        confirmLabel="Restore / add back"
        isLoading={restoreReplacedRecipient.isPending}
        onClose={() => setReplacedRecipientToRestore(null)}
        onConfirm={() => {
          if (!replacedRecipientToRestore) return;
          const target = replacedRecipientToRestore;
          setRestoreReplacedError(null);
          restoreReplacedRecipient.mutate(
            {
              broadcastGroupId: group.id,
              clientGroupId: target.client_group_id,
              resolutionId: target.resolution_id,
            },
            {
              onSuccess: () => {
                setReplacedRecipientToRestore(null);
                setRecipientRosterTab("all");
                setSuccessMessage(
                  `${target.name || target.normalized_phone_number} was restored to the active recipient list.`,
                );
              },
              onError: (restoreError) => {
                setReplacedRecipientToRestore(null);
                setRestoreReplacedError(
                  readErrorMessage(
                    restoreError,
                    "Could not restore this recipient.",
                  ),
                );
              },
            },
          );
        }}
      />

      <ConfirmDialog
        isOpen={!isArchived && Boolean(recipientToRemove)}
        title="Remove recipient?"
        description={`${recipientToRemove?.name || recipientToRemove?.phone_number || "This recipient"} will be removed from this broadcast. Their existing delivery records remain available for audit purposes.`}
        confirmLabel="Remove Recipient"
        variant="danger"
        isLoading={deleteRecipient.isPending}
        onClose={() => setRecipientToRemove(null)}
        onConfirm={() => {
          if (!recipientToRemove) return;
          deleteRecipient.mutate(
            { groupId: group.id, recipientId: recipientToRemove.id },
            {
              onSuccess: () => {
                setRecipientToRemove(null);
                setSuccessMessage("Recipient removed from this broadcast.");
              },
              onError: (removeError) => {
                setRecipientError(
                  readErrorMessage(
                    removeError,
                    "Could not remove this recipient.",
                  ),
                );
                setRecipientToRemove(null);
              },
            },
          );
        }}
      />
    </>
  );
}
