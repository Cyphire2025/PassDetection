"use client";

import {
  FileSpreadsheet,
  Info,
  MessageCircle,
  MoreVertical,
  Plus,
  Send,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  Input,
  Skeleton,
} from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import {
  ContactEditor,
  DialogFrame,
  ErrorBanner,
  type ManualContact,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import type {
  WhatsAppBroadcastGroup,
  WhatsAppMessageType,
  WhatsAppPreviewResponse,
  WhatsAppRecipientInput,
  WhatsAppRecipientMessageStatus,
  WhatsAppSendResponse,
  WhatsAppSupportContactInput,
} from "../api/whatsapp.api";
import {
  useAddWhatsAppRecipients,
  useCreateWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useDeleteWhatsAppRecipient,
  usePreviewWhatsAppMessage,
  useSendWhatsAppPassportLink,
  useSendWhatsAppWelcome,
  useUpdateWhatsAppGroup,
  useWhatsAppBatchStatus,
  useWhatsAppGroup,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";
import {
  countEligibleRecipients,
  getMessageStatus,
} from "../utils/recipient-delivery";
import { mergeWhatsAppSendProgress } from "../utils/send-progress";

type MessageTarget = {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
};

type PersistedBatch = {
  id: string;
  startedAt: number;
  skipped_already_sent?: number;
  skipped_in_progress?: number;
  skipped_delivery_unknown?: number;
};

const LAST_BATCH_STORAGE_KEY = "passdetection:whatsapp:last-batch";

export function WhatsAppPage() {
  const { data: groups = [], isLoading, error } = useWhatsAppGroups();
  const createGroup = useCreateWhatsAppGroup();
  const deleteGroup = useDeleteWhatsAppGroup();
  const sendWelcome = useSendWhatsAppWelcome();
  const sendPassportLink = useSendWhatsAppPassportLink();
  const [showCreate, setShowCreate] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [recipientListGroup, setRecipientListGroup] =
    useState<WhatsAppBroadcastGroup | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<WhatsAppBroadcastGroup | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [messageTarget, setMessageTarget] = useState<MessageTarget | null>(
    null,
  );
  const [lastSend, setLastSend] = useState<WhatsAppSendResponse | null>(null);
  const [persistedBatch, setPersistedBatch] = useState<PersistedBatch | null>(
    () => {
      if (typeof window === "undefined") return null;
      try {
        const saved = window.sessionStorage.getItem(LAST_BATCH_STORAGE_KEY);
        return saved ? (JSON.parse(saved) as PersistedBatch) : null;
      } catch {
        return null;
      }
    },
  );
  const activeBatchId = lastSend?.batch_id ?? persistedBatch?.id ?? null;
  const { data: currentBatch } = useWhatsAppBatchStatus(
    activeBatchId,
    persistedBatch?.startedAt ?? null,
  );
  const displayedSend = mergeWhatsAppSendProgress(
    currentBatch,
    lastSend,
    persistedBatch,
  );
  useEffect(() => {
    if (
      !currentBatch ||
      currentBatch.queued > 0 ||
      typeof window === "undefined"
    )
      return;
    window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
  }, [currentBatch]);

  const openMessagePreview = (
    group: WhatsAppBroadcastGroup,
    messageType: WhatsAppMessageType,
  ) => {
    setOpenMenuId(null);
    setMessageTarget({ group, messageType });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            WhatsApp Broadcast
          </h1>
          <p className="mt-1 text-slate-500">
            Create recipient lists and send approved trip messages to each
            person individually.
          </p>
        </div>
        <Button type="button" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" />
          Create
        </Button>
      </div>

      {displayedSend && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            displayedSend.failed > 0 || displayedSend.delivery_unknown > 0
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : displayedSend.queued > 0
                ? "border-blue-200 bg-blue-50 text-blue-800"
                : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {displayedSend.queued > 0 && (
            <>
              {displayedSend.queued} message
              {displayedSend.queued === 1 ? " is" : "s are"} queued for
              individual delivery.
            </>
          )}
          {displayedSend.sent > 0 && (
            <>{displayedSend.sent} submitted to WhatsApp. </>
          )}
          {displayedSend.skipped_already_sent > 0 && (
            <>
              {displayedSend.skipped_already_sent} skipped because this message
              was already sent successfully.{" "}
            </>
          )}
          {displayedSend.skipped_in_progress > 0 && (
            <>
              {displayedSend.skipped_in_progress} skipped because delivery is
              already in progress.{" "}
            </>
          )}
          {displayedSend.skipped_delivery_unknown > 0 && (
            <>
              {displayedSend.skipped_delivery_unknown} skipped because an
              earlier delivery outcome is unknown; review before taking manual
              action.{" "}
            </>
          )}
          {displayedSend.failed > 0 && (
            <>
              {displayedSend.failed} failed; review the provider configuration
              or recipient numbers.{" "}
            </>
          )}
          {displayedSend.delivery_unknown > 0 && (
            <>
              {displayedSend.delivery_unknown} delivery outcome
              {displayedSend.delivery_unknown === 1 ? " is" : "s are"} unknown;
              review the recipient list before taking manual action.
            </>
          )}
        </div>
      )}

      {actionError && <ErrorBanner message={actionError} />}

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          WhatsApp lists could not be loaded. Check that the backend is
          reachable.
        </div>
      ) : isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : groups.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center px-6 py-16 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <MessageCircle className="h-6 w-6" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-900">
              No WhatsApp lists yet
            </h2>
            <p className="mt-1 max-w-md text-sm text-slate-500">
              Add recipients manually or upload an Excel file to prepare the
              first individual broadcast.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
                  <tr>
                    <th className="px-6 py-4">Group Name</th>
                    <th className="px-6 py-4">Organising Company</th>
                    <th className="px-6 py-4">Recipients</th>
                    <th className="px-6 py-4">Updated</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {groups.map((group) => (
                    <tr
                      key={group.id}
                      className="transition-colors hover:bg-slate-50/50"
                    >
                      <td className="px-6 py-4">
                        <div className="font-medium text-slate-900">
                          {group.name}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Shown inside client messages
                        </div>
                      </td>
                      <td className="px-6 py-4 text-slate-700">
                        {group.organizing_company_name || "Not set"}
                      </td>
                      <td className="px-6 py-4 text-slate-700">
                        <span className="inline-flex items-center gap-1.5">
                          <Users className="h-4 w-4 text-slate-400" />
                          {group.recipient_count}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-600">
                        {formatDateTime(group.updated_at)}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex justify-end">
                          <ActionMenu
                            group={group}
                            isOpen={openMenuId === group.id}
                            isSending={
                              sendWelcome.isPending ||
                              sendPassportLink.isPending
                            }
                            onOpen={() =>
                              setOpenMenuId(
                                openMenuId === group.id ? null : group.id,
                              )
                            }
                            onClose={() => setOpenMenuId(null)}
                            onRecipients={() => {
                              setOpenMenuId(null);
                              setRecipientListGroup(group);
                            }}
                            onWelcome={() =>
                              openMessagePreview(group, "welcome")
                            }
                            onPassportLink={() =>
                              openMessagePreview(group, "passport_link")
                            }
                            onDelete={() => {
                              setActionError(null);
                              setOpenMenuId(null);
                              setDeleteTarget(group);
                            }}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {showCreate && (
        <CreateBroadcastDialog
          isLoading={createGroup.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={async (payload) => {
            await createGroup.mutateAsync(payload);
            setShowCreate(false);
          }}
        />
      )}

      {messageTarget && (
        <MessagePreviewDialog
          group={messageTarget.group}
          messageType={messageTarget.messageType}
          isSending={sendWelcome.isPending || sendPassportLink.isPending}
          onClose={() => setMessageTarget(null)}
          onSend={async ({ passportLink, messageContent }) => {
            const result =
              messageTarget.messageType === "welcome"
                ? await sendWelcome.mutateAsync({
                    groupId: messageTarget.group.id,
                    messageContent,
                  })
                : await sendPassportLink.mutateAsync({
                    groupId: messageTarget.group.id,
                    passportLink,
                    messageContent,
                  });
            setLastSend(result);
            if (result.batch_id && typeof window !== "undefined") {
              const savedBatch = {
                id: result.batch_id,
                startedAt: Date.now(),
                skipped_already_sent: result.skipped_already_sent,
                skipped_in_progress: result.skipped_in_progress,
                skipped_delivery_unknown: result.skipped_delivery_unknown,
              };
              setPersistedBatch(savedBatch);
              window.sessionStorage.setItem(
                LAST_BATCH_STORAGE_KEY,
                JSON.stringify(savedBatch),
              );
            } else if (typeof window !== "undefined") {
              setPersistedBatch(null);
              window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
            }
            setMessageTarget(null);
          }}
        />
      )}

      {recipientListGroup && (
        <RecipientListDialog
          group={recipientListGroup}
          onClose={() => setRecipientListGroup(null)}
        />
      )}

      <ConfirmDialog
        isOpen={Boolean(deleteTarget)}
        title="Delete WhatsApp broadcast?"
        description={`This permanently deletes ${deleteTarget?.name ?? "this broadcast"}, its recipient list, and its delivery history. This action cannot be undone.`}
        confirmLabel="Delete Broadcast"
        variant="danger"
        isLoading={deleteGroup.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) return;
          deleteGroup.mutate(deleteTarget.id, {
            onSuccess: () => setDeleteTarget(null),
            onError: (deleteError) => {
              setActionError(
                readErrorMessage(
                  deleteError,
                  "Could not delete this WhatsApp broadcast.",
                ),
              );
              setDeleteTarget(null);
            },
          });
        }}
      />
    </div>
  );
}

function ActionMenu({
  group,
  isOpen,
  isSending,
  onOpen,
  onClose,
  onRecipients,
  onWelcome,
  onPassportLink,
  onDelete,
}: {
  group: WhatsAppBroadcastGroup;
  isOpen: boolean;
  isSending: boolean;
  onOpen: () => void;
  onClose: () => void;
  onRecipients: () => void;
  onWelcome: () => void;
  onPassportLink: () => void;
  onDelete: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{
    left: number;
    top: number;
  } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!ref.current?.contains(target) && !menuRef.current?.contains(target))
        onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen, onClose]);

  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-sm hover:bg-slate-50"
        onClick={() => {
          const rect = buttonRef.current?.getBoundingClientRect();
          if (rect) {
            const menuWidth = 240;
            const menuHeight = 192;
            const top =
              rect.bottom + 8 + menuHeight > window.innerHeight
                ? Math.max(8, rect.top - menuHeight - 8)
                : rect.bottom + 8;
            setMenuPosition({
              left: Math.max(
                8,
                Math.min(
                  window.innerWidth - menuWidth - 8,
                  rect.right - menuWidth,
                ),
              ),
              top,
            });
          }
          onOpen();
        }}
        aria-label={`Open actions for ${group.name}`}
        aria-expanded={isOpen}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {isOpen &&
        menuPosition &&
        createPortal(
          <div
            ref={menuRef}
            className="fixed z-[70] w-60 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl"
            style={{ left: menuPosition.left, top: menuPosition.top }}
          >
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50"
              onClick={onRecipients}
            >
              <Users className="h-4 w-4" />
              Recipient List
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={isSending}
              onClick={onWelcome}
            >
              <Send className="h-4 w-4" />
              Send Welcome Message
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={isSending}
              onClick={onPassportLink}
            >
              <Send className="h-4 w-4" />
              Send Passport Link
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 border-t border-slate-100 px-4 py-3 text-left text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              disabled={isSending}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" />
              Delete Broadcast
            </button>
          </div>,
          document.body,
        )}
    </div>
  );
}
function RecipientListDialog({
  group,
  onClose,
}: {
  group: WhatsAppBroadcastGroup;
  onClose: () => void;
}) {
  const {
    data: detail,
    isLoading,
    error: loadError,
  } = useWhatsAppGroup(group.id);
  const updateGroup = useUpdateWhatsAppGroup();
  const addRecipientsMutation = useAddWhatsAppRecipients();
  const deleteRecipient = useDeleteWhatsAppRecipient();
  const [name, setName] = useState(group.name);
  const [organizingCompanyName, setOrganizingCompanyName] = useState(
    group.organizing_company_name,
  );
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
  const [file, setFile] = useState<File | null>(null);
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [recipientError, setRecipientError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [recipientToRemove, setRecipientToRemove] = useState<
    (WhatsAppRecipientInput & { id: string }) | null
  >(null);
  const initializedGroupRef = useRef<string | null>(null);

  useEffect(() => {
    if (!detail || initializedGroupRef.current === detail.id) return;
    initializedGroupRef.current = detail.id;
    setName(detail.name);
    setOrganizingCompanyName(detail.organizing_company_name);
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
    setDetailsError(null);
    setSuccessMessage(null);
    if (!name.trim() || !organizingCompanyName.trim()) {
      setDetailsError("Enter both the broadcast name and organising company.");
      return;
    }
    if (supportContacts.length === 0) {
      setDetailsError("Keep at least one customer support contact.");
      return;
    }
    try {
      const updated = await updateGroup.mutateAsync({
        groupId: group.id,
        name: name.trim(),
        organizingCompanyName: organizingCompanyName.trim(),
        supportContacts,
      });
      setName(updated.name);
      setOrganizingCompanyName(updated.organizing_company_name);
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
    }
  };

  const addRecipients = async () => {
    setRecipientError(null);
    setSuccessMessage(null);
    if (contacts.length === 0 && !file) {
      setRecipientError(
        "Add at least one named recipient or select an Excel file.",
      );
      return;
    }
    if (!recipientOptInConfirmed) {
      setRecipientError(
        "Confirm that the new recipients agreed to receive WhatsApp updates.",
      );
      return;
    }
    try {
      const updated = await addRecipientsMutation.mutateAsync({
        groupId: group.id,
        contacts,
        recipientOptInConfirmed,
        file,
      });
      setContacts([]);
      setFile(null);
      setRecipientOptInConfirmed(false);
      setSuccessMessage(
        `Recipient list updated. It now contains ${updated.recipient_count} recipient${updated.recipient_count === 1 ? "" : "s"}.`,
      );
    } catch (updateError) {
      setRecipientError(
        readErrorMessage(updateError, "Could not add these recipients."),
      );
    }
  };
  const messageTypes = [
    "welcome",
    "passport_link",
    ...(detail?.recipients.flatMap(
      (recipient) =>
        recipient.message_statuses?.map((status) => status.message_type) ?? [],
    ) ?? []),
  ].filter(
    (messageType, index, allTypes) => allTypes.indexOf(messageType) === index,
  );

  return (
    <>
      <DialogFrame
        title={`Recipient List - ${detail?.name ?? group.name}`}
        onClose={onClose}
        widthClass="max-w-5xl"
      >
        {loadError ? (
          <ErrorBanner message="The recipient list could not be loaded." />
        ) : isLoading || !detail ? (
          <div className="space-y-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-48" />
          </div>
        ) : (
          <div className="space-y-6">
            <section className="rounded-xl border border-slate-200 p-4">
              <div>
                <h3 className="font-semibold text-slate-900">
                  Broadcast details
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  These details appear in the approved messages sent to
                  recipients.
                </p>
              </div>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <Input
                  label="Broadcast name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  maxLength={100}
                />
                <Input
                  label="Organising company"
                  value={organizingCompanyName}
                  onChange={(event) =>
                    setOrganizingCompanyName(event.target.value)
                  }
                  maxLength={100}
                />
              </div>
              <div className="mt-4">
                <ContactEditor
                  title="Customer support contacts"
                  description="These contacts appear at the end of both approved messages. You can keep up to three."
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
                    !organizingCompanyName.trim() ||
                    supportContacts.length === 0 ||
                    (name.trim() === detail.name &&
                      organizingCompanyName.trim() ===
                        detail.organizing_company_name &&
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

            <section>
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-900">
                    Current recipients
                  </h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Delivery checks prevent a successfully sent message type
                    from being sent to the same person twice.
                  </p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">
                  {detail.recipient_count} total
                </span>
              </div>

              <div className="mt-3 max-h-72 overflow-auto rounded-xl border border-slate-200">
                <table className="w-full min-w-[680px] text-left text-sm">
                  <thead className="sticky top-0 border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3">Recipient</th>
                      <th className="px-4 py-3">WhatsApp number</th>
                      {messageTypes.map((messageType) => (
                        <th key={messageType} className="px-4 py-3">
                          {formatMessageType(messageType)}
                        </th>
                      ))}
                      <th className="px-4 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {detail.recipients.map((recipient) => {
                      return (
                        <tr key={recipient.id}>
                          <td className="px-4 py-3 font-medium text-slate-900">
                            {recipient.name || "Unnamed recipient"}
                          </td>
                          <td className="px-4 py-3 text-slate-600">
                            {recipient.normalized_phone_number}
                          </td>
                          {messageTypes.map((messageType) => (
                            <td key={messageType} className="px-4 py-3">
                              <DeliveryBadge
                                status={getMessageStatus(
                                  recipient,
                                  messageType,
                                )}
                              />
                            </td>
                          ))}
                          <td className="px-4 py-3 text-right">
                            <button
                              type="button"
                              className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50"
                              disabled={
                                detail.recipient_count <= 1 ||
                                deleteRecipient.isPending
                              }
                              title={
                                detail.recipient_count <= 1
                                  ? "A broadcast must keep at least one recipient"
                                  : undefined
                              }
                              onClick={() =>
                                setRecipientToRemove({
                                  id: recipient.id,
                                  name: recipient.name,
                                  phone_number: recipient.phone_number,
                                })
                              }
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/30 p-4">
              <div>
                <h3 className="font-semibold text-slate-900">Add recipients</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Add people manually or import an Excel file. Existing phone
                  numbers are safely ignored.
                </p>
              </div>

              <ContactEditor
                title="Manual recipients"
                description="Names are required because each approved message is personalised."
                value={manual}
                contacts={contacts}
                onValueChange={setManual}
                onAdd={addManualContact}
                onRemove={(index) =>
                  setContacts((current) =>
                    current.filter((_, itemIndex) => itemIndex !== index),
                  )
                }
              />

              <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-4 hover:bg-slate-50">
                <span className="flex min-w-0 items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                    <FileSpreadsheet className="h-5 w-5" />
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-900">
                      {file ? file.name : "Upload additional Excel contacts"}
                    </span>
                    <span className="block text-sm text-slate-500">
                      Use .xlsx or .xlsm with name and phone/WhatsApp columns.
                    </span>
                  </span>
                </span>
                <Upload className="h-5 w-5 shrink-0 text-slate-400" />
                <input
                  type="file"
                  accept=".xlsx,.xlsm"
                  className="sr-only"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </label>

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

              {recipientError && <ErrorBanner message={recipientError} />}
              <div className="flex justify-end">
                <Button
                  type="button"
                  isLoading={addRecipientsMutation.isPending}
                  disabled={
                    (contacts.length === 0 && !file) || !recipientOptInConfirmed
                  }
                  onClick={addRecipients}
                >
                  <Plus className="h-4 w-4" />
                  Add Recipients
                </Button>
              </div>
            </section>

            {successMessage && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
                {successMessage}
              </div>
            )}
          </div>
        )}
      </DialogFrame>

      <ConfirmDialog
        isOpen={Boolean(recipientToRemove)}
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
function DeliveryBadge({
  status,
}: {
  status: WhatsAppRecipientMessageStatus | null;
}) {
  const isInProgress =
    status?.status === "queued" || status?.status === "processing";
  const isDeliveryUnknown = status?.status === "delivery_unknown";
  const label = status?.already_sent
    ? "Sent"
    : isDeliveryUnknown
      ? "Delivery unknown - review"
      : isInProgress
        ? "In progress"
        : status?.status === "failed"
          ? "Failed - retry"
          : "Not sent";
  const style = status?.already_sent
    ? "bg-emerald-50 text-emerald-700"
    : isDeliveryUnknown
      ? "bg-amber-100 text-amber-800"
      : isInProgress
        ? "bg-blue-50 text-blue-700"
        : status?.status === "failed"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-500";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}
    >
      {label}
    </span>
  );
}

function formatMessageType(messageType: string): string {
  if (messageType === "welcome") return "Welcome message";
  if (messageType === "passport_link") return "Passport link";
  return messageType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function CreateBroadcastDialog({
  isLoading,
  onClose,
  onSubmit,
}: {
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    organizingCompanyName: string;
    contacts: WhatsAppRecipientInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    file: File | null;
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [organizingCompanyName, setOrganizingCompanyName] = useState("");
  const [manual, setManual] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [support, setSupport] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [supportContacts, setSupportContacts] = useState<ManualContact[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const addContact = (
    value: ManualContact,
    setter: React.Dispatch<React.SetStateAction<ManualContact[]>>,
    resetter: React.Dispatch<React.SetStateAction<ManualContact>>,
    label: string,
  ) => {
    setError(null);
    if (!value.name.trim() || !value.phone_number.trim()) {
      setError(`Enter both the ${label} name and WhatsApp number.`);
      return;
    }
    setter((current) => [
      ...current,
      { name: value.name.trim(), phone_number: value.phone_number.trim() },
    ]);
    resetter({ name: "", phone_number: "" });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Enter a group name.");
      return;
    }
    if (!organizingCompanyName.trim()) {
      setError("Enter the organising company name.");
      return;
    }
    if (contacts.length === 0 && !file) {
      setError("Add at least one named recipient or upload an Excel file.");
      return;
    }
    if (supportContacts.length === 0) {
      setError("Add at least one customer support contact.");
      return;
    }
    if (!recipientOptInConfirmed) {
      setError(
        "Confirm that recipients agreed to receive trip updates on WhatsApp.",
      );
      return;
    }
    try {
      await onSubmit({
        name: name.trim(),
        organizingCompanyName: organizingCompanyName.trim(),
        contacts,
        supportContacts,
        recipientOptInConfirmed,
        file,
      });
    } catch (submitError) {
      setError(
        readErrorMessage(submitError, "Could not save this WhatsApp list."),
      );
    }
  };

  return (
    <DialogFrame title="Create WhatsApp Broadcast Group" onClose={onClose}>
      <p className="text-sm text-slate-500">
        Each saved recipient receives a separate WhatsApp message; this does not
        create a shared WhatsApp chat group.
      </p>
      <form className="mt-5 space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-4 md:grid-cols-2">
          <Input
            label="Group name"
            hint="This name will be visible to clients inside the message."
            placeholder="Vietnam Leadership Trip 2026"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <Input
            label="Organising company name"
            hint="This company name will be visible to clients inside the message."
            placeholder="Bluechip"
            value={organizingCompanyName}
            onChange={(event) => setOrganizingCompanyName(event.target.value)}
            required
          />
        </div>

        <ContactEditor
          title="Recipients"
          description="Names are required because every message is personalised as Dear [Name]."
          value={manual}
          contacts={contacts}
          onValueChange={setManual}
          onAdd={() => addContact(manual, setContacts, setManual, "recipient")}
          onRemove={(index) =>
            setContacts((current) =>
              current.filter((_, itemIndex) => itemIndex !== index),
            )
          }
        />

        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-dashed border-slate-300 px-4 py-4 hover:bg-slate-50">
          <span className="flex min-w-0 items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <FileSpreadsheet className="h-5 w-5" />
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium text-slate-900">
                {file ? file.name : "Upload Excel contacts"}
              </span>
              <span className="block text-sm text-slate-500">
                Use .xlsx or .xlsm with name and phone/WhatsApp columns. Bare
                10-digit numbers use India (+91); include country codes for all
                others.
              </span>
            </span>
          </span>
          <Upload className="h-5 w-5 shrink-0 text-slate-400" />
          <input
            type="file"
            accept=".xlsx,.xlsm"
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>

        <ContactEditor
          title="Customer support contacts"
          description="Every contact added here appears at the end of both messages. You can add up to three."
          value={support}
          contacts={supportContacts}
          onValueChange={setSupport}
          onAdd={() => {
            if (supportContacts.length >= 3) {
              setError("You can add up to three customer support contacts.");
              return;
            }
            addContact(
              support,
              setSupportContacts,
              setSupport,
              "support contact",
            );
          }}
          onRemove={(index) =>
            setSupportContacts((current) =>
              current.filter((_, itemIndex) => itemIndex !== index),
            )
          }
        />

        <label className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-slate-700">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            checked={recipientOptInConfirmed}
            onChange={(event) =>
              setRecipientOptInConfirmed(event.target.checked)
            }
          />
          <span>
            I confirm these recipients agreed to receive trip-related WhatsApp
            updates and can request that messages stop.
          </span>
        </label>

        {error && <ErrorBanner message={error} />}

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Save List
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}

function MessagePreviewDialog({
  group,
  messageType,
  isSending,
  onClose,
  onSend,
}: {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
  isSending: boolean;
  onClose: () => void;
  onSend: (payload: {
    passportLink: string;
    messageContent: string;
  }) => Promise<void>;
}) {
  const { data: detail, isLoading: isLoadingDetail } = useWhatsAppGroup(
    group.id,
  );
  const previewRequest = usePreviewWhatsAppMessage();
  const [passportLink, setPassportLink] = useState("");
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [previewRecipientId, setPreviewRecipientId] = useState<string | null>(
    null,
  );
  const [preview, setPreview] = useState<WhatsAppPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const previewSequence = useRef(0);
  const previewMutate = previewRequest.mutate;

  useEffect(() => {
    const sequence = ++previewSequence.current;
    const timeout = window.setTimeout(() => {
      previewMutate(
        {
          groupId: group.id,
          draft: {
            message_type: messageType,
            passport_link:
              messageType === "passport_link" ? passportLink : null,
            message_content: messageContent,
            recipient_id: previewRecipientId,
          },
        },
        {
          onSuccess: (response) => {
            if (sequence !== previewSequence.current) return;
            setPreview(response);
            setMessageContent((current) => current ?? response.message_content);
            setError(null);
          },
          onError: (previewError) => {
            if (sequence !== previewSequence.current) return;
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
    return () => window.clearTimeout(timeout);
  }, [
    group.id,
    messageContent,
    messageType,
    passportLink,
    previewMutate,
    previewRecipientId,
  ]);

  const resolvedMessageContent = (
    messageContent ??
    preview?.message_content ??
    ""
  ).trim();
  const eligibleRecipientCount =
    preview?.eligible_recipient_count ??
    (detail
      ? countEligibleRecipients(detail.recipients, messageType)
      : undefined) ??
    group.recipient_count;
  const canSend = Boolean(
    detail?.recipient_opt_in_confirmed &&
    detail.support_contacts.length > 0 &&
    resolvedMessageContent &&
    eligibleRecipientCount > 0 &&
    (messageType === "welcome" || passportLink.trim()),
  );

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (!resolvedMessageContent) {
      setError(
        "Add text before sending. Meta requires this editable template section to contain text.",
      );
      return;
    }
    if (messageType === "passport_link" && !passportLink.trim()) {
      setError("Paste the passport upload link before sending.");
      return;
    }
    try {
      await onSend({
        passportLink: passportLink.trim(),
        messageContent: resolvedMessageContent,
      });
    } catch (sendError) {
      setError(
        readErrorMessage(
          sendError,
          "WhatsApp could not submit this broadcast.",
        ),
      );
    }
  };

  return (
    <DialogFrame
      title={
        messageType === "welcome"
          ? "Preview Welcome Message"
          : "Preview Passport Link Message"
      }
      onClose={onClose}
      widthClass="max-w-5xl"
    >
      <form className="space-y-5" onSubmit={handleSend}>
        <div className="flex gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-blue-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            This box supplies Meta Body variable{" "}
            {messageType === "welcome" ? "{{3}}" : "{{4}}"} and can change
            before each send. The remaining wording is fixed in the approved
            Meta template; changing that fixed text requires Meta approval
            again.
          </p>
        </div>

        {messageType === "passport_link" && (
          <Input
            label="Passport upload link"
            hint="This secure link is inserted separately into every recipient's message."
            placeholder="https://..."
            value={passportLink}
            onChange={(event) => setPassportLink(event.target.value)}
            required
          />
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <label className="block text-sm font-medium text-slate-700">
              Editable message section
              <textarea
                className="mt-1.5 min-h-56 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                value={messageContent ?? preview?.message_content ?? ""}
                onChange={(event) => setMessageContent(event.target.value)}
                maxLength={600}
              />
              {messageContent !== null && !resolvedMessageContent && (
                <span className="mt-1.5 block text-xs font-normal text-amber-700">
                  Add text before sending. Meta requires this editable template
                  section to contain text.
                </span>
              )}
            </label>
            {detail && detail.recipients.length > 1 && (
              <label className="block text-sm font-medium text-slate-700">
                Preview recipient
                <select
                  className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  value={previewRecipientId ?? preview?.recipient_id ?? ""}
                  onChange={(event) =>
                    setPreviewRecipientId(event.target.value)
                  }
                >
                  {detail.recipients.map((recipient) => (
                    <option key={recipient.id} value={recipient.id}>
                      {recipient.name || "Guest"} -{" "}
                      {recipient.normalized_phone_number}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-slate-700">
                Individual WhatsApp preview
              </h3>
              <span className="text-xs text-slate-500">
                {eligibleRecipientCount} eligible of{" "}
                {preview?.recipient_count ?? group.recipient_count}
              </span>
            </div>
            <div className="mt-1.5 min-h-96 rounded-2xl bg-[#e5ddd5] p-4 shadow-inner">
              <div className="ml-auto max-w-[94%] rounded-xl rounded-tr-sm bg-[#dcf8c6] p-3 text-sm leading-5 text-slate-900 shadow-sm">
                {preview ? (
                  <p className="whitespace-pre-wrap">
                    {preview.rendered_message}
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
                {preview.already_sent_count > 0 && (
                  <p className="font-medium text-emerald-700">
                    {preview.already_sent_count} previous recipient
                    {preview.already_sent_count === 1 ? "" : "s"} will be
                    skipped automatically.
                  </p>
                )}
                {preview.in_progress_count > 0 && (
                  <p className="font-medium text-blue-700">
                    {preview.in_progress_count} recipient
                    {preview.in_progress_count === 1 ? " is" : "s are"} already
                    queued and will not be queued twice.
                  </p>
                )}
                {preview.uncertain_recipient_count > 0 && (
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
            Loading recipient and support details...
          </p>
        )}
        {detail && !detail.recipient_opt_in_confirmed && (
          <ErrorBanner message="This older list has no recorded recipient opt-in confirmation. Create a new list before sending." />
        )}
        {detail && detail.support_contacts.length === 0 && (
          <ErrorBanner message="This older list has no customer support contacts. Create a new list before sending." />
        )}
        {preview &&
          eligibleRecipientCount === 0 &&
          preview.already_sent_count === preview.recipient_count && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
              This message has already been sent successfully to every recipient
              in this broadcast. No duplicate messages will be sent.
            </div>
          )}
        {preview &&
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
        {preview &&
          eligibleRecipientCount === 0 &&
          preview.uncertain_recipient_count === 0 &&
          preview.in_progress_count > 0 && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
              No new deliveries can be queued: {preview.already_sent_count}{" "}
              already sent and {preview.in_progress_count} currently in
              progress.
            </div>
          )}
        {error && <ErrorBanner message={error} />}

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
            Send individually to {eligibleRecipientCount}
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}
