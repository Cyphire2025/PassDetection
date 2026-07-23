"use client";

import {
  AlertTriangle,
  Bold,
  CheckCircle2,
  FileSpreadsheet,
  Info,
  Loader2,
  MessageCircle,
  MoreVertical,
  Pencil,
  Plus,
  RotateCw,
  Send,
  Trash2,
  Upload,
  Users,
} from "lucide-react";
import Image from "next/image";
import {
  type Dispatch,
  type FormEvent,
  Fragment,
  type SetStateAction,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
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
import {
  parseWhatsAppBoldSegments,
  toggleWhatsAppBold,
} from "../utils/whatsapp-formatting";
import {
  whatsappApi,
  type WhatsAppBroadcastGroup,
  type WhatsAppMessageType,
  type WhatsAppPreviewResponse,
  type WhatsAppRejectedContact,
  type WhatsAppRejectedContactInput,
  type WhatsAppRecipientInput,
  type WhatsAppRecipientMessageStatus,
  type WhatsAppSendResponse,
  type WhatsAppSupportContactInput,
} from "../api/whatsapp.api";
import {
  useAddWhatsAppRecipients,
  useCreateWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useDeleteWhatsAppRecipient,
  usePreviewWhatsAppMessage,
  useResolveWhatsAppRejectedContact,
  useResendWhatsAppRecipientMessage,
  useSendWhatsAppPassportLink,
  useSendWhatsAppWelcome,
  useUpdateWhatsAppGroup,
  useUpdateWhatsAppRecipientPhone,
  useWhatsAppBatchStatus,
  useWhatsAppGroup,
  useWhatsAppGroups,
  useWhatsAppRecipientRoster,
} from "../hooks/use-whatsapp";
import {
  countEligibleRecipients,
  getMessageStatus,
  hasAlreadySentMessage,
  isRecipientEligible,
} from "../utils/recipient-delivery";
import {
  mergeRecipientImportRejectedRows,
  mergeRecipientImportPreview,
  type RecipientImportRejectedRowWithSource,
} from "../utils/recipient-import";
import {
  filterRecipientRosterItems,
  type WhatsAppRecipientRosterTab,
} from "../utils/recipient-roster";
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

type RecipientResendTarget = {
  recipientId: string;
  recipientName: string;
  phoneNumber: string;
  messageType: WhatsAppMessageType;
  action: "resend" | "retry";
};

type RejectedContactDraft = RecipientImportRejectedRowWithSource;

type RejectedContactCorrection = {
  id: string;
  name: string;
  phoneNumber: string;
  optInConfirmed: boolean;
};

const LAST_BATCH_STORAGE_KEY = "passdetection:whatsapp:last-batch";
const MAX_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024;
const WELCOME_IMAGE_TYPES = new Set(["image/jpeg", "image/png"]);
function importedFieldLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const ROSTER_SOURCE_FIELD_KEYS = new Set([
  "source_file",
  "source_order",
  "source_sheet",
  "source_row",
]);

function visibleImportedFieldEntries(
  importedFields: Record<string, string> | null | undefined,
): Array<[string, string]> {
  return Object.entries(importedFields ?? {})
    .filter(([key]) => !ROSTER_SOURCE_FIELD_KEYS.has(key))
    .sort(([left], [right]) =>
      importedFieldLabel(left).localeCompare(importedFieldLabel(right)),
    );
}

function toRejectedContactInputs(
  contacts: RejectedContactDraft[],
): WhatsAppRejectedContactInput[] {
  return contacts.map((contact) => ({
    source_file_name: contact.source_file_name,
    sheet_name: contact.sheet_name,
    row_number: contact.row_number,
    raw_name: contact.raw_name,
    raw_phone_number: contact.raw_phone_number,
    reason_code: contact.reason_code,
    imported_fields: contact.imported_fields,
  }));
}

type RecipientImportState =
  | { status: "idle" }
  | { status: "loading"; fileName: string }
  | {
      status: "success";
      fileName: string;
      acceptedCount: number;
      addedCount: number;
      duplicateCount: number;
      rejectedCount: number;
      rejectedRows: RejectedContactDraft[];
      rejectedRowsTruncated: boolean;
      omittedRejectedCount: number;
    }
  | { status: "error"; fileName: string; message: string };

function useRecipientExcelPreview({
  contacts,
  setContacts,
  excludedPhoneNumbers = [],
  onStart,
}: {
  contacts: ManualContact[];
  setContacts: Dispatch<SetStateAction<ManualContact[]>>;
  excludedPhoneNumbers?: string[];
  onStart: () => void;
}) {
  const [importState, setImportState] = useState<RecipientImportState>({
    status: "idle",
  });
  const requestIdRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const contactsRef = useRef(contacts);
  const excludedPhoneNumbersRef = useRef(excludedPhoneNumbers);
  const rejectedContactsRef = useRef<RejectedContactDraft[]>([]);
  const omittedRejectedCountsRef = useRef(new Map<string, number>());
  const [rejectedContacts, setRejectedContacts] = useState<
    RejectedContactDraft[]
  >([]);

  useEffect(() => {
    contactsRef.current = contacts;
  }, [contacts]);

  useEffect(() => {
    excludedPhoneNumbersRef.current = excludedPhoneNumbers;
  }, [excludedPhoneNumbers]);

  useEffect(
    () => () => {
      requestIdRef.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const previewFile = async (file: File) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    onStart();
    setImportState({ status: "loading", fileName: file.name });

    try {
      const preview = await whatsappApi.previewContacts(file, controller.signal);
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;

      const merged = mergeRecipientImportPreview(
        contactsRef.current,
        preview,
        excludedPhoneNumbersRef.current,
      );
      contactsRef.current = merged.contacts;
      setContacts(merged.contacts);
      const accumulatedRejectedRows = mergeRecipientImportRejectedRows(
        rejectedContactsRef.current,
        merged.rejectedRows,
        file.name,
      );
      rejectedContactsRef.current = accumulatedRejectedRows;
      omittedRejectedCountsRef.current.set(
        file.name,
        merged.omittedRejectedCount,
      );
      const accumulatedOmittedRejectedCount = Array.from(
        omittedRejectedCountsRef.current.values(),
      ).reduce(
        (total, omittedCount) => total + omittedCount,
        0,
      );
      const accumulatedRejectedCount =
        accumulatedRejectedRows.length + accumulatedOmittedRejectedCount;
      setRejectedContacts(accumulatedRejectedRows);
      setImportState({
        status: "success",
        fileName: file.name,
        acceptedCount: merged.acceptedCount,
        addedCount: merged.addedCount,
        duplicateCount: merged.duplicateCount,
        rejectedCount: accumulatedRejectedCount,
        rejectedRows: accumulatedRejectedRows,
        rejectedRowsTruncated: accumulatedOmittedRejectedCount > 0,
        omittedRejectedCount: accumulatedOmittedRejectedCount,
      });
    } catch (previewError) {
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      setImportState({
        status: "error",
        fileName: file.name,
        message: readErrorMessage(
          previewError,
          "The Excel contacts could not be read. Check the columns and try again.",
        ),
      });
    } finally {
      if (requestId === requestIdRef.current) controllerRef.current = null;
    }
  };

  const resetImport = () => {
    requestIdRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    rejectedContactsRef.current = [];
    omittedRejectedCountsRef.current.clear();
    setRejectedContacts([]);
    setImportState({ status: "idle" });
  };

  return { importState, previewFile, rejectedContacts, resetImport };
}

function ExcelRecipientImport({
  state,
  onFile,
  label,
}: {
  state: RecipientImportState;
  onFile: (file: File) => Promise<void>;
  label: string;
}) {
  const isLoading = state.status === "loading";
  const fileName = state.status === "idle" ? null : state.fileName;
  const rejectionTitleId = useId();

  return (
    <div className="space-y-2">
      <label
        className={`flex items-center justify-between gap-4 rounded-xl border border-dashed px-4 py-4 ${
          isLoading
            ? "cursor-wait border-blue-300 bg-blue-50/60"
            : "cursor-pointer border-slate-300 bg-white hover:bg-slate-50"
        }`}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : state.status === "success" && state.rejectedCount > 0 ? (
              <AlertTriangle className="h-5 w-5 text-amber-600" />
            ) : state.status === "success" ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            ) : (
              <FileSpreadsheet className="h-5 w-5" />
            )}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-900">
              {fileName ?? label}
            </span>
            <span className="block text-sm text-slate-500">
              {isLoading
                ? "Reading and validating recipients..."
                : "Use .xlsx or .xlsm with name and phone/WhatsApp columns."}
            </span>
          </span>
        </span>
        <Upload className="h-5 w-5 shrink-0 text-slate-400" />
        <input
          type="file"
          accept=".xlsx,.xlsm"
          className="sr-only"
          disabled={isLoading}
          onChange={(event) => {
            const selectedFile = event.currentTarget.files?.[0] ?? null;
            event.currentTarget.value = "";
            if (selectedFile) void onFile(selectedFile);
          }}
        />
      </label>

      <div>
        {state.status === "success" && (
          <div className="space-y-3">
            <p
              role="status"
              className={`text-sm ${
                state.rejectedCount > 0
                  ? "text-amber-800"
                  : "text-emerald-700"
              }`}
            >
              {state.addedCount} new recipient
              {state.addedCount === 1 ? "" : "s"} added.
              {state.duplicateCount > 0
                ? ` ${state.duplicateCount} contact${state.duplicateCount === 1 ? " was" : "s were"} skipped because the number is already in this list or broadcast.`
                : " You can edit or remove the accepted recipients above before saving."}
            </p>
            {state.rejectedCount > 0 && (
              <section
                className="rounded-xl border border-amber-200 bg-amber-50/60 p-3"
                aria-labelledby={rejectionTitleId}
              >
                <h4
                  id={rejectionTitleId}
                  className="font-semibold text-amber-900"
                >
                  {state.rejectedCount} spreadsheet row
                  {state.rejectedCount === 1 ? "" : "s"} need attention
                </h4>
                <p className="mt-1 text-xs text-amber-800">
                  Valid recipients were kept. The rows shown below will be
                  saved with this broadcast for correction, but they cannot
                  receive messages.
                  {state.rejectedRowsTruncated &&
                    ` ${state.omittedRejectedCount} additional rejected row${state.omittedRejectedCount === 1 ? " was" : "s were"} counted but could not be included in this preview.`}
                </p>
                {state.rejectedRows.length > 0 && (
                  <div
                    className="mt-3 space-y-2"
                    aria-label="Rejected spreadsheet rows"
                  >
                    {state.rejectedRows.map((row, index) => (
                      <article
                        key={`${row.source_file_name}:${row.sheet_name}:${row.row_number}:${index}`}
                        className="rounded-lg border border-amber-200 bg-white p-3 text-xs text-slate-700"
                      >
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Source</span>
                            <p className="break-words">{row.source_file_name}</p>
                          </div>
                          <div>
                            <span className="font-semibold text-amber-900">Sheet and row</span>
                            <p>{row.sheet_name}, row {row.row_number}</p>
                          </div>
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Entered name</span>
                            <p className="break-words">{row.raw_name?.trim() || "Blank"}</p>
                          </div>
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Entered phone</span>
                            <p className="break-all font-mono">{row.raw_phone_number?.trim() || "Blank"}</p>
                          </div>
                        </div>
                        <p className="mt-3 break-words text-amber-900">{row.reason}</p>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}
          </div>
        )}
        {state.status === "error" && (
          <p role="alert" className="text-sm text-red-700">
            {state.message}
          </p>
        )}
      </div>
    </div>
  );
}

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
              <table className="w-full min-w-[700px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
                  <tr>
                    <th className="px-6 py-4">Group Name</th>
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
                          Used in approved trip wording
                        </div>
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
          onSend={async ({
            passportIntro,
            passportLink,
            messageContent,
            headerImage,
            headerImageId,
            recipientIds,
            supportContactIds,
          }) => {
            const result =
              messageTarget.messageType === "welcome"
                ? await sendWelcome.mutateAsync({
                    groupId: messageTarget.group.id,
                    messageContent,
                    image: headerImage,
                    headerImageId,
                    recipientIds,
                  })
                : await sendPassportLink.mutateAsync({
                    groupId: messageTarget.group.id,
                    passportIntro,
                    passportLink,
                    messageContent,
                    image: headerImage,
                    headerImageId,
                    recipientIds,
                    supportContactIds,
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
          key={recipientListGroup.id}
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
              disabled={isSending || group.recipient_count === 0}
              title={
                group.recipient_count === 0
                  ? "Add a valid recipient before sending"
                  : undefined
              }
              onClick={onWelcome}
            >
              <Send className="h-4 w-4" />
              Send Welcome Message
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={isSending || group.recipient_count === 0}
              title={
                group.recipient_count === 0
                  ? "Add a valid recipient before sending"
                  : undefined
              }
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

function RejectedRosterRows({
  contact,
  serialNumber,
  messageColumnCount,
  correction,
  isSaving,
  onEdit,
  onCorrectionChange,
  onCancel,
  onSave,
}: {
  contact: WhatsAppRejectedContact;
  serialNumber: number;
  messageColumnCount: number;
  correction: RejectedContactCorrection | null;
  isSaving: boolean;
  onEdit: () => void;
  onCorrectionChange: (value: RejectedContactCorrection) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const isEditing = correction?.id === contact.id;
  const importedEntries = visibleImportedFieldEntries(
    contact.imported_fields,
  );

  return (
    <Fragment>
      <tr className="bg-amber-50/40">
        <td className="px-4 py-3 text-center font-semibold text-slate-500">
          {serialNumber}
        </td>
        <td className="px-4 py-3">
          <div className="font-medium text-slate-900">
            {contact.raw_name?.trim() || "Unnamed rejected contact"}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {contact.source_file_name} · {contact.sheet_name}, row{" "}
            {contact.row_number}
          </p>
          {importedEntries.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                View {importedEntries.length} imported detail
                {importedEntries.length === 1 ? "" : "s"}
              </summary>
              <dl className="mt-2 grid min-w-64 gap-2 rounded-lg bg-white p-3 sm:grid-cols-2">
                {importedEntries.map(([key, value]) => (
                  <div key={key} className="min-w-0">
                    <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      {importedFieldLabel(key)}
                    </dt>
                    <dd className="break-words text-xs font-normal text-slate-700">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </td>
        <td className="px-4 py-3">
          <span className="break-all font-mono text-slate-700">
            {contact.raw_phone_number?.trim() || "Missing"}
          </span>
        </td>
        {Array.from({ length: messageColumnCount }, (_, index) => (
          <td key={index} className="px-4 py-3">
            <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
              Rejected
            </span>
          </td>
        ))}
        <td className="px-4 py-3 text-right">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
            aria-expanded={isEditing}
            onClick={onEdit}
          >
            <Pencil className="h-3.5 w-3.5" />
            Correct
          </button>
        </td>
      </tr>
      {isEditing && correction && (
        <tr className="bg-amber-50/40">
          <td colSpan={messageColumnCount + 4} className="px-4 pb-4 pt-0">
            <div className="rounded-xl border border-amber-200 bg-white p-4">
              <p className="mb-3 break-words rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                {contact.reason}
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                  Corrected name
                  <input
                    type="text"
                    value={correction.name}
                    className="mt-1.5 w-full rounded-md border border-amber-300 px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        name: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                  Corrected WhatsApp number
                  <input
                    type="tel"
                    value={correction.phoneNumber}
                    autoFocus
                    className="mt-1.5 w-full rounded-md border border-amber-300 px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        phoneNumber: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-amber-100 pt-3">
                <label className="flex items-start gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={correction.optInConfirmed}
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        optInConfirmed: event.target.checked,
                      })
                    }
                  />
                  Recipient agreed to WhatsApp updates
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="rounded-md px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                    disabled={isSaving}
                    onClick={onCancel}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      isSaving
                      || !correction.name.trim()
                      || !correction.phoneNumber.trim()
                      || !correction.optInConfirmed
                    }
                    onClick={onSave}
                  >
                    Save and add
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
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
    refetch: refetchGroup,
  } = useWhatsAppGroup(group.id);
  const updateGroup = useUpdateWhatsAppGroup();
  const addRecipientsMutation = useAddWhatsAppRecipients();
  const deleteRecipient = useDeleteWhatsAppRecipient();
  const updateRecipientPhone = useUpdateWhatsAppRecipientPhone();
  const resolveRejectedContact = useResolveWhatsAppRejectedContact();
  const resendRecipientMessage = useResendWhatsAppRecipientMessage();
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
  const [rejectedContactEdit, setRejectedContactEdit] =
    useState<RejectedContactCorrection | null>(null);
  const [rejectedContactError, setRejectedContactError] = useState<
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
      });
      const savedRejectedCount = rejectedContacts.length;
      setContacts([]);
      resetImport();
      setRecipientOptInConfirmed(false);
      setRecipientRosterTab("all");
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

  const resendSelectedMessage = async (payload: {
    passportIntro: string;
    passportLink: string;
    messageContent: string;
    headerImage: File | null;
    headerImageId: string | null;
    recipientIds: string[] | null;
    supportContactIds: string[] | null;
  }) => {
    if (
      !recipientToResend
      || resendRecipientMessage.isPending
      || resendInFlightRef.current
    ) return;

    const target = recipientToResend;
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
        messageContent: payload.messageContent,
        image: payload.headerImage,
        headerImageId: payload.headerImageId,
        supportContactIds: payload.supportContactIds,
      });
      setRecipientToResend(null);
      await refetchGroup();
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

  const messageTypes = [
    "welcome",
    "passport_link",
    ...(recipientRoster?.items.flatMap((item) =>
      item.kind === "recipient"
        ? item.recipient.message_statuses.map((status) => status.message_type)
        : [],
    ) ?? []),
  ].filter(
    (messageType, index, allTypes) => allTypes.indexOf(messageType) === index,
  );
  const visibleRosterItems = recipientRoster
    ? filterRecipientRosterItems(recipientRoster.items, recipientRosterTab)
    : [];
  const rosterTabs: Array<{
    id: WhatsAppRecipientRosterTab;
    label: string;
  }> = [
    { id: "all", label: "All" },
    { id: "sent", label: "Sent" },
    { id: "failed", label: "Failed" },
    { id: "rejected", label: "Rejected" },
  ];
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
      {!recipientToResend && (
        <DialogFrame
          title={`Recipient List - ${detail?.name ?? group.name}`}
          onClose={onClose}
          isBusy={
            updateGroup.isPending
            || addRecipientsMutation.isPending
            || deleteRecipient.isPending
            || updateRecipientPhone.isPending
            || resolveRejectedContact.isPending
            || resendRecipientMessage.isPending
            || Boolean(recipientToRemove)
          }
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

            <section>
              <div>
                <h3 className="font-semibold text-slate-900">
                  Current recipients
                </h3>
                <p className="mt-1 text-sm text-slate-500">
                  Review everyone in their original import order. Sent and
                  Failed can overlap when different message types have
                  different outcomes.
                </p>
              </div>

              <div
                className="mt-4 flex flex-wrap gap-2"
                role="tablist"
                aria-label="Recipient delivery filters"
              >
                {rosterTabs.map((tab) => {
                  const isActive = recipientRosterTab === tab.id;
                  const count = recipientRoster?.counts[tab.id] ?? 0;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      role="tab"
                      aria-selected={isActive}
                      aria-controls="recipient-roster-panel"
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold transition ${
                        isActive
                          ? "border-blue-600 bg-blue-600 text-white"
                          : tab.id === "failed"
                            ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
                            : tab.id === "rejected"
                              ? "border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
                              : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                      }`}
                      onClick={() => {
                        setRecipientRosterTab(tab.id);
                        setRejectedContactEdit(null);
                        setRejectedContactError(null);
                      }}
                    >
                      {tab.label}
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          isActive
                            ? "bg-white/20 text-white"
                            : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {count}
                      </span>
                    </button>
                  );
                })}
              </div>

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

              <div
                id="recipient-roster-panel"
                role="tabpanel"
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
                    No {recipientRosterTab === "all" ? "" : `${recipientRosterTab} `}
                    contacts were found.
                  </p>
                ) : (
                  <div className="max-h-96 overflow-auto rounded-xl border border-slate-200">
                    <table className="w-full min-w-[880px] text-left text-sm">
                      <thead className="sticky top-0 z-10 border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        <tr>
                          <th className="w-14 px-4 py-3 text-center">#</th>
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
                        {visibleRosterItems.map((item, index) => {
                          const serialNumber = index + 1;
                          if (item.kind === "rejected") {
                            const contact = item.rejected_contact;
                            return (
                              <RejectedRosterRows
                                key={`rejected:${contact.id}`}
                                contact={contact}
                                serialNumber={serialNumber}
                                messageColumnCount={messageTypes.length}
                                correction={rejectedContactEdit}
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
                                    await refetchRecipientRoster();
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
                          const importedEntries =
                            visibleImportedFieldEntries(
                              recipient.imported_fields,
                            );
                          return (
                            <tr key={`recipient:${recipient.id}`}>
                              <td className="px-4 py-3 text-center font-semibold text-slate-500">
                                {serialNumber}
                              </td>
                              <td className="px-4 py-3">
                                <div className="font-medium text-slate-900">
                                  {recipient.name || "Unnamed recipient"}
                                </div>
                                {importedEntries.length > 0 && (
                                  <details className="mt-1">
                                    <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                                      View {importedEntries.length}{" "}
                                      imported detail
                                      {importedEntries.length === 1 ? "" : "s"}
                                    </summary>
                                    <dl className="mt-2 grid min-w-64 gap-2 rounded-lg bg-slate-50 p-3 sm:grid-cols-2">
                                      {importedEntries.map(([key, value]) => (
                                          <div key={key} className="min-w-0">
                                            <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                                              {importedFieldLabel(key)}
                                            </dt>
                                            <dd className="break-words text-xs font-normal text-slate-700">
                                              {value}
                                            </dd>
                                          </div>
                                        ))}
                                    </dl>
                                  </details>
                                )}
                              </td>
                              <td className="px-4 py-3 text-slate-600">
                                {editingRecipientId === recipient.id ? (
                                  <div className="flex min-w-64 items-center gap-2">
                                    <input
                                      type="tel"
                                      value={editedPhoneNumber}
                                      autoFocus
                                      aria-label={`WhatsApp number for ${recipient.name || "unnamed recipient"}`}
                                      className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2.5 py-1.5 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                                      onChange={(event) =>
                                        setEditedPhoneNumber(event.target.value)
                                      }
                                    />
                                    <button
                                      type="button"
                                      className="rounded-md px-2 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                                      disabled={
                                        updateRecipientPhone.isPending
                                        || !editedPhoneNumber.trim()
                                      }
                                      onClick={async () => {
                                        setRecipientError(null);
                                        try {
                                          await updateRecipientPhone.mutateAsync({
                                            groupId: group.id,
                                            recipientId: recipient.id,
                                            phoneNumber:
                                              editedPhoneNumber.trim(),
                                          });
                                          setEditingRecipientId(null);
                                          setSuccessMessage(
                                            `WhatsApp number updated for ${recipient.name || "this recipient"}. Previous message statuses are ready to retry on the new number.`,
                                          );
                                        } catch (phoneError) {
                                          setRecipientError(
                                            readErrorMessage(
                                              phoneError,
                                              "Could not update this WhatsApp number.",
                                            ),
                                          );
                                        }
                                      }}
                                    >
                                      Save
                                    </button>
                                    <button
                                      type="button"
                                      className="rounded-md px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                                      disabled={updateRecipientPhone.isPending}
                                      onClick={() => setEditingRecipientId(null)}
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                ) : (
                                  <div className="flex items-center gap-2">
                                    <span>
                                      {recipient.normalized_phone_number}
                                    </span>
                                    <button
                                      type="button"
                                      className="rounded-md p-1 text-blue-700 hover:bg-blue-50"
                                      aria-label={`Edit WhatsApp number for ${recipient.name || "unnamed recipient"}`}
                                      title="Edit WhatsApp number"
                                      onClick={() => {
                                        setRecipientError(null);
                                        setEditingRecipientId(recipient.id);
                                        setEditedPhoneNumber(
                                          recipient.phone_number,
                                        );
                                      }}
                                    >
                                      <Pencil className="h-3.5 w-3.5" />
                                    </button>
                                  </div>
                                )}
                              </td>
                              {messageTypes.map((messageType) => {
                                const messageStatus = getMessageStatus(
                                  recipient,
                                  messageType,
                                );
                                const knownMessageType =
                                  isWhatsAppMessageType(messageType);
                                const canResend =
                                  knownMessageType
                                  && hasAlreadySentMessage(
                                    recipient,
                                    messageType,
                                  );
                                const canRetry =
                                  knownMessageType
                                  && messageStatus?.status === "failed";
                                const resendBlocked =
                                  messageStatus?.resend_blocked ?? false;
                                const latestResendStatus =
                                  messageStatus?.latest_resend_status;
                                const isResendProcessing =
                                  latestResendStatus === "queued"
                                  || latestResendStatus === "processing";
                                const needsResendReview =
                                  latestResendStatus === "delivery_unknown";
                                return (
                                  <td key={messageType} className="px-4 py-3">
                                    <div className="flex flex-wrap items-center gap-2">
                                      <DeliveryBadge status={messageStatus} />
                                      {(canResend || canRetry) && (
                                        <button
                                          type="button"
                                          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                                          disabled={
                                            resendRecipientMessage.isPending
                                            || resendBlocked
                                          }
                                          title={
                                            needsResendReview
                                              ? "The latest resend outcome is unknown. Review it before sending another duplicate."
                                              : isResendProcessing
                                                ? "A resend is already in progress for this person."
                                                : undefined
                                          }
                                          aria-label={`${canRetry ? "Retry" : "Resend"} ${formatMessageType(messageType)} to ${recipient.name || "unnamed recipient"}`}
                                          onClick={() => {
                                            setResendError(null);
                                            setResendNotice(null);
                                            setLastResendTarget(null);
                                            setRecipientToResend({
                                              recipientId: recipient.id,
                                              recipientName:
                                                recipient.name
                                                || "Unnamed recipient",
                                              phoneNumber:
                                                recipient.normalized_phone_number,
                                              messageType,
                                              action: canRetry
                                                ? "retry"
                                                : "resend",
                                            });
                                          }}
                                        >
                                          <RotateCw className="h-3.5 w-3.5" />
                                          {needsResendReview
                                            ? "Review required"
                                            : isResendProcessing
                                              ? "Resending..."
                                              : canRetry
                                                ? "Retry"
                                                : "Resend"}
                                        </button>
                                      )}
                                      {latestResendStatus === "failed" && (
                                        <span className="text-xs font-medium text-red-600">
                                          Last resend failed
                                        </span>
                                      )}
                                      {(
                                        latestResendStatus === "sent"
                                        || latestResendStatus === "delivered"
                                        || latestResendStatus === "read"
                                      ) && (
                                        <span className="text-xs font-medium text-emerald-700">
                                          Resent
                                        </span>
                                      )}
                                    </div>
                                  </td>
                                );
                              })}
                              <td className="px-4 py-3 text-right">
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50"
                                  disabled={
                                    detail.recipient_count <= 1
                                    || deleteRecipient.isPending
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
                )}
              </div>
            </section>

            <section className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/30 p-4">
              <div>
                <h3 className="font-semibold text-slate-900">Add recipients</h3>
                <p className="mt-1 text-sm text-slate-500">
                  Add people manually or import an Excel file. Existing phone
                  numbers are safely ignored, and invalid rows can be saved for
                  correction.
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

            {successMessage && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
                {successMessage}
              </div>
            )}
          </div>
        )}
        </DialogFrame>
      )}

      {recipientToResend && (
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
          ? "Failed"
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

function isWhatsAppMessageType(
  messageType: string,
): messageType is WhatsAppMessageType {
  return messageType === "welcome" || messageType === "passport_link";
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
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
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
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitInFlightRef = useRef(false);
  const { importState, previewFile, rejectedContacts } =
    useRecipientExcelPreview({
      contacts,
      setContacts,
      onStart: () => setError(null),
    });

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
    if (importState.status === "loading") {
      setError("Wait for the Excel contacts to finish loading.");
      return;
    }
    if (!name.trim()) {
      setError("Enter a group name.");
      return;
    }
    if (contacts.length === 0 && rejectedContacts.length === 0) {
      setError(
        "Add at least one named recipient or import rejected rows for correction.",
      );
      return;
    }
    if (
      contacts.some(
        (contact) => !contact.name.trim() || !contact.phone_number.trim(),
      )
    ) {
      setError("Every recipient needs both a name and WhatsApp number.");
      return;
    }
    if (supportContacts.length === 0) {
      setError("Add at least one customer support contact.");
      return;
    }
    if (contacts.length > 0 && !recipientOptInConfirmed) {
      setError(
        "Confirm that recipients agreed to receive trip updates on WhatsApp.",
      );
      return;
    }
    if (isLoading || submitInFlightRef.current) return;
    submitInFlightRef.current = true;
    try {
      await onSubmit({
        name: name.trim(),
        contacts,
        rejectedContacts: toRejectedContactInputs(rejectedContacts),
        supportContacts,
        recipientOptInConfirmed:
          contacts.length > 0 && recipientOptInConfirmed,
      });
    } catch (submitError) {
      setError(
        readErrorMessage(submitError, "Could not save this WhatsApp list."),
      );
    } finally {
      submitInFlightRef.current = false;
    }
  };

  return (
    <DialogFrame
      title="Create WhatsApp Broadcast Group"
      onClose={onClose}
      isBusy={isLoading}
    >
      <p className="text-sm text-slate-500">
        Each saved recipient receives a separate WhatsApp message; this does not
        create a shared WhatsApp chat group.
      </p>
      <form className="mt-5 space-y-5" onSubmit={handleSubmit}>
        <div className="max-w-xl">
          <Input
            label="Group name"
            hint="Used to identify this broadcast and prefill the approved trip wording."
            placeholder="Vietnam Leadership Trip 2026"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={100}
            required
          />
        </div>

        <ContactEditor
          title="Recipients"
          description="Names are required so staff can identify each recipient and review delivery status."
          value={manual}
          contacts={contacts}
          onValueChange={(value) => {
            setError(null);
            setManual(value);
          }}
          onAdd={() => addContact(manual, setContacts, setManual, "recipient")}
          onRemove={(index) => {
            setError(null);
            setContacts((current) =>
              current.filter((_, itemIndex) => itemIndex !== index),
            );
          }}
          onContactChange={(index, contact) => {
            setError(null);
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
          label="Upload Excel contacts"
        />

        <ContactEditor
          title="Passport-link support contacts"
          description="These contacts appear only at the end of the Passport Link message. Welcome messages do not include them."
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

        {contacts.length > 0 ? (
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
              I confirm these recipients agreed to receive trip-related
              WhatsApp updates and can request that messages stop.
            </span>
          </label>
        ) : rejectedContacts.length > 0 ? (
          <p className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-sm text-amber-800">
            This broadcast currently has no valid recipients. Its rejected
            spreadsheet rows will be saved for correction and cannot receive
            WhatsApp messages.
          </p>
        ) : null}

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
          <Button
            type="submit"
            isLoading={isLoading}
            disabled={importState.status === "loading"}
          >
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
  const [recipientSelectionMode, setRecipientSelectionMode] = useState<
    "all" | "custom"
  >("all");
  const [selectedRecipientIds, setSelectedRecipientIds] = useState<string[]>(
    [],
  );
  const [selectedSupportContactIds, setSelectedSupportContactIds] = useState<
    string[] | null
  >(null);
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
  const resolvedSupportContactIds = useMemo(
    () => {
      if (selectedSupportContactIds !== null) {
        return selectedSupportContactIds.slice(0, 1);
      }
      const firstContactId = detail?.support_contacts[0]?.id;
      return firstContactId ? [firstContactId] : [];
    },
    [detail?.support_contacts, selectedSupportContactIds],
  );

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
      setError("Bold formatting must fit within the 600-character message limit.");
      return;
    }
    setValue(update.value);
    window.requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(update.selectionStart, update.selectionEnd);
    });
  };

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
              messageType === "passport_link"
              && !targetRecipient
              && recipientSelectionMode === "custom"
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
              controller.signal.aborted
              || sequence !== previewSequence.current
            ) return;
            setPreview(response);
            setPassportIntro((current) =>
              current ?? response.passport_intro ?? null
            );
            setPassportLink((current) =>
              current ?? response.passport_link ?? null
            );
            setMessageContent((current) => current ?? response.message_content);
            setHeaderImageId((current) =>
              headerImage
                ? current
                : current ?? response.header_image_id ?? null
            );
            setError(null);
          },
          onError: (previewError) => {
            if (
              controller.signal.aborted
              || sequence !== previewSequence.current
            ) return;
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
  const targetRecipientDetail = targetRecipient && detail
    ? detail.recipients.find(
        (recipient) => recipient.id === targetRecipient.recipientId,
      )
    : undefined;
  const targetMessageStatus = targetRecipientDetail
    ? getMessageStatus(targetRecipientDetail, messageType)
    : undefined;
  const canResendTarget = !targetRecipient || Boolean(
    targetRecipient.action === "retry"
      ? targetMessageStatus?.status === "failed"
      : targetMessageStatus?.already_sent && !targetMessageStatus.resend_blocked,
  );
  const eligibleRecipients = detail?.recipients.filter((recipient) =>
    isRecipientEligible(recipient, messageType),
  ) ?? [];
  const selectedEligibleRecipients =
    messageType === "passport_link"
    && !targetRecipient
    && recipientSelectionMode === "custom"
      ? eligibleRecipients.filter((recipient) =>
          selectedRecipientIds.includes(recipient.id),
        )
      : eligibleRecipients;
  const eligibleRecipientCount = targetRecipient
    ? 1
    : recipientSelectionMode === "custom"
      ? selectedEligibleRecipients.length
      : preview?.eligible_recipient_count ??
      (detail
        ? countEligibleRecipients(detail.recipients, messageType)
        : undefined) ??
      group.recipient_count;
  const canSend = Boolean(
    detail?.recipient_opt_in_confirmed &&
    (messageType === "welcome" || resolvedSupportContactIds.length > 0) &&
    resolvedMessageContent &&
    eligibleRecipientCount > 0 &&
    canResendTarget &&
    hasHeaderImage &&
    (messageType === "welcome" ||
      (resolvedPassportIntro && resolvedPassportLink)),
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
    if (!hasHeaderImage) {
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
      messageType === "passport_link"
      && resolvedSupportContactIds.length === 0
    ) {
      setError("Select at least one support contact for this Passport Link message.");
      return;
    }
    if (
      messageType === "passport_link"
      && !targetRecipient
      && recipientSelectionMode === "custom"
      && selectedRecipientIds.length === 0
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
          messageType === "passport_link"
          && !targetRecipient
          && recipientSelectionMode === "custom"
            ? selectedRecipientIds
            : null,
        supportContactIds:
          messageType === "passport_link"
            ? resolvedSupportContactIds
            : null,
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
      title={
        `${targetRecipient ? targetRecipient.action === "retry" ? "Retry" : "Resend" : "Preview"} ${
          messageType === "welcome" ? "Welcome Message" : "Passport Link Message"
        }`
      }
      onClose={onClose}
      isBusy={isSending}
      widthClass="max-w-5xl"
    >
      <form className="space-y-5" onSubmit={handleSend}>
        <div className="flex gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-blue-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          {messageType === "welcome" ? (
            <p>
              The uploaded picture is the required Meta IMAGE header. The text
              below supplies BODY variable {"{{1}}"}. Dear Delegates and the
              remaining wording stay fixed in the approved template.
            </p>
          ) : (
            <p>
              The picture is the required Meta IMAGE header. The introduction
              supplies BODY variable {"{{1}}"}, the passport upload link
              supplies BODY variable {"{{2}}"}, and the instructions supply
              BODY variable {"{{3}}"}. The remaining wording stays fixed in the
              approved template.
            </p>
          )}
        </div>

        {preview?.content_source !== undefined
          && preview.content_source !== "default" && (
          <div
            role="status"
            className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800"
          >
            {preview.content_source === "latest_recipient"
              ? `Loaded the latest saved message for this recipient. You can edit it before ${targetRecipient?.action === "retry" ? "retrying" : "resending"}.`
              : "Loaded the most recent message used for this broadcast. You can edit it before sending to the remaining recipients."}
          </div>
        )}

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

        {messageType === "passport_link" && (
          <Input
            label="Passport upload link"
            hint="This secure link supplies Meta BODY variable {{2}} for every recipient."
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
                  Passport link introduction (BODY {"{{1}}"})
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
                    value={
                      passportIntro ?? preview?.passport_intro ?? ""
                    }
                    onChange={(event) => setPassportIntro(event.target.value)}
                    maxLength={600}
                  />
                </div>
                {passportIntro !== null && !resolvedPassportIntro && (
                  <span className="mt-1.5 block text-xs font-normal text-amber-700">
                    Add the introduction used for Meta BODY variable {"{{1}}"}.
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
                  ? "Welcome trip message (BODY {{1}})"
                  : "Passport instructions (BODY {{3}})"}
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
                  Add text before sending. Meta requires this editable template
                  section to contain text.
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
                        if (firstEligibleId) setPreviewRecipientId(firstEligibleId);
                      }}
                    />
                    Custom select
                  </label>
                </div>
                {recipientSelectionMode === "custom" && (
                  <details className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3" open>
                    <summary className="cursor-pointer text-sm font-semibold text-slate-800">
                      {selectedEligibleRecipients.length} recipient
                      {selectedEligibleRecipients.length === 1 ? "" : "s"} selected
                    </summary>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="text-xs font-semibold text-blue-700 hover:text-blue-800"
                        onClick={() => {
                          const ids = eligibleRecipients.map((recipient) => recipient.id);
                          setSelectedRecipientIds(ids);
                          setPreviewRecipientId(ids[0] ?? null);
                        }}
                      >
                        Select all
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
                    <div className="mt-2 max-h-52 space-y-1 overflow-y-auto pr-1">
                      {eligibleRecipients.map((recipient) => (
                        <label
                          key={recipient.id}
                          className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-white"
                        >
                          <input
                            type="checkbox"
                            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            checked={selectedRecipientIds.includes(recipient.id)}
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
                              } else if (previewRecipientId === recipient.id) {
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
                        <span className="font-medium text-slate-800">{contact.name}</span>
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
                to <strong>{targetRecipient.recipientName}</strong>
                {" "}({targetRecipient.phoneNumber}). No other recipient will
                receive this {targetRecipient.action}.
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
          <ErrorBanner message={`This ${targetRecipient.action} can no longer be submitted because its latest delivery state changed. Refresh the recipient list before trying again.`} />
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
            {targetRecipient
              ? `${targetRecipient.action === "retry" ? "Retry" : "Resend"} to ${targetRecipient.recipientName}`
              : `Send individually to ${eligibleRecipientCount}`}
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}
