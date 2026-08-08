"use client";

import {
  Activity,
  CheckCircle2,
  Clock3,
  MessageCircle,
  MoreVertical,
  Plus,
  Send,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Button, ConfirmDialog, Skeleton } from "@/components/ui";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
  WorkspaceToolbar,
} from "@/components/shared/workspace-ui";
import { formatDateTime } from "@/lib/utils/format";
import {
  ErrorBanner,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import {
  type WhatsAppBroadcastGroup,
  type WhatsAppMessageType,
  type WhatsAppSendResponse,
} from "../api/whatsapp.api";
import {
  useCreateWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useSendWhatsAppPassportLink,
  useSendWhatsAppReminder,
  useSendWhatsAppWelcome,
  useWhatsAppBatchStatus,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";
import { mergeWhatsAppSendProgress } from "../utils/send-progress";

const CreateBroadcastDialog = dynamic(
  () => import("./whatsapp-create-broadcast-dialog").then((module) => module.CreateBroadcastDialog),
  { loading: () => <DialogLoadingState label="Loading broadcast editor" /> },
);
const MessagePreviewDialog = dynamic(
  () => import("./whatsapp-message-preview-dialog").then((module) => module.MessagePreviewDialog),
  { loading: () => <DialogLoadingState label="Loading message preview" /> },
);
const RecipientListDialog = dynamic(
  () => import("./whatsapp-recipient-dialog").then((module) => module.RecipientListDialog),
  { loading: () => <DialogLoadingState label="Loading recipient list" /> },
);

type MessageTarget = {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
};

type PersistedBatch = {
  id: string;
  startedAt: number;
  groupId?: string;
  skipped_already_sent?: number;
  skipped_in_progress?: number;
  skipped_delivery_unknown?: number;
};

const LAST_BATCH_STORAGE_KEY = "passdetection:whatsapp:last-batch";

function formatCompactDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "recently";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

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

export function WhatsAppPage() {
  const queryClient = useQueryClient();
  const { data: groups = [], isLoading, error } = useWhatsAppGroups();
  const createGroup = useCreateWhatsAppGroup();
  const deleteGroup = useDeleteWhatsAppGroup();
  const sendWelcome = useSendWhatsAppWelcome();
  const sendPassportLink = useSendWhatsAppPassportLink();
  const sendReminder = useSendWhatsAppReminder();
  const [showCreate, setShowCreate] = useState(false);
  const [groupQuery, setGroupQuery] = useState("");
  const deferredGroupQuery = useDeferredValue(groupQuery);
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(null);
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
  const refreshedTerminalBatchRef = useRef<string | null>(null);
  const clearMissingBatchTracking = useCallback((missingBatchId: string) => {
    setLastSend((current) =>
      current?.batch_id === missingBatchId ? null : current,
    );
    setPersistedBatch((current) =>
      current?.id === missingBatchId ? null : current,
    );

    if (typeof window === "undefined") return;
    const saved = window.sessionStorage.getItem(LAST_BATCH_STORAGE_KEY);
    if (!saved) return;
    try {
      const storedBatch = JSON.parse(saved) as Partial<PersistedBatch>;
      if (storedBatch.id === missingBatchId) {
        window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
      }
    } catch {
      window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
    }
  }, []);
  const activeBatchId = lastSend?.batch_id ?? persistedBatch?.id ?? null;
  const { data: currentBatch } = useWhatsAppBatchStatus(
    activeBatchId,
    persistedBatch?.startedAt ?? null,
    clearMissingBatchTracking,
  );
  const displayedSend = mergeWhatsAppSendProgress(
    currentBatch,
    lastSend,
    persistedBatch,
  );
  const filteredGroups = useMemo(() => {
    const normalized = deferredGroupQuery.trim().toLocaleLowerCase();
    if (!normalized) return groups;
    return groups.filter((group) => group.name.toLocaleLowerCase().includes(normalized));
  }, [deferredGroupQuery, groups]);
  const totalEligibleRecipients = useMemo(
    () => groups.reduce((total, group) => total + group.recipient_count, 0),
    [groups],
  );
  const totalContacts = useMemo(
    () => groups.reduce((total, group) => total + group.total_contact_count, 0),
    [groups],
  );
  const latestUpdatedAt = useMemo(
    () => groups.reduce<string | null>((latest, group) => {
      if (!latest || Date.parse(group.updated_at) > Date.parse(latest)) return group.updated_at;
      return latest;
    }, null),
    [groups],
  );
  useEffect(() => {
    if (
      !currentBatch ||
      currentBatch.queued > 0 ||
      typeof window === "undefined"
    )
      return;
    window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
    if (refreshedTerminalBatchRef.current === currentBatch.batch_id) return;
    refreshedTerminalBatchRef.current = currentBatch.batch_id;
    const completedGroupId = persistedBatch?.groupId;
    if (!completedGroupId) return;
    void Promise.all([
      queryClient.invalidateQueries({
        queryKey: ["whatsapp", "groups"],
      }),
      queryClient.invalidateQueries({
        queryKey: ["whatsapp", "groups", completedGroupId],
      }),
      queryClient.invalidateQueries({
        queryKey: [
          "whatsapp",
          "groups",
          completedGroupId,
          "recipient-roster",
        ],
      }),
    ]);
  }, [currentBatch, persistedBatch?.groupId, queryClient]);
  const openMessagePreview = (
    group: WhatsAppBroadcastGroup,
    messageType: WhatsAppMessageType,
  ) => {
    setOpenMenuKey(null);
    setMessageTarget({ group, messageType });
  };
  const isSendingAnyMessage =
    sendWelcome.isPending || sendPassportLink.isPending || sendReminder.isPending;
  const renderGroupActionMenu = (
    group: WhatsAppBroadcastGroup,
    surface: "mobile" | "desktop",
  ) => {
    const menuKey = `${surface}:${group.id}`;
    return (
      <ActionMenu
        group={group}
        isOpen={openMenuKey === menuKey}
        isSending={isSendingAnyMessage}
        onOpen={() =>
          setOpenMenuKey((current) => (current === menuKey ? null : menuKey))
        }
        onClose={() => setOpenMenuKey(null)}
        onRecipients={() => {
          setOpenMenuKey(null);
          setRecipientListGroup(group);
        }}
        onWelcome={() => openMessagePreview(group, "welcome")}
        onPassportLink={() => openMessagePreview(group, "passport_link")}
        onReminder={() => openMessagePreview(group, "reminder")}
        onDelete={() => {
          setActionError(null);
          setOpenMenuKey(null);
          setDeleteTarget(group);
        }}
      />
    );
  };

  return (
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        eyebrow="Passenger communication centre"
        title="WhatsApp"
        description="Build controlled recipient groups, review contact readiness, preview approved trip wording, and monitor every individual send batch."
        icon={MessageCircle}
        accent="emerald"
        context={(
          <>
            <WorkspaceHeaderContext icon={ShieldCheck}>Approved individual messaging</WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={Users}>{totalEligibleRecipients.toLocaleString()} eligible recipients</WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <Button
            type="button"
            onClick={() => setShowCreate(true)}
            className="bg-white text-[#123f73] shadow-sm hover:bg-emerald-50 active:bg-emerald-100"
          >
          <Plus className="h-4 w-4" />
            Create Broadcast
          </Button>
        )}
      />

      <WorkspaceSummaryStrip label="WhatsApp communication summary">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Broadcast groups"
              value={groups.length.toLocaleString()}
              helper="recipient lists"
              icon={MessageCircle}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Eligible recipients"
              value={totalEligibleRecipients.toLocaleString()}
              helper="ready to message"
              icon={CheckCircle2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Visible contacts"
              value={totalContacts.toLocaleString()}
              helper="including exceptions"
              icon={Users}
            />
            <WorkspaceSummaryItem
              label="Current batch"
              value={(displayedSend?.queued ?? 0).toLocaleString()}
              helper={displayedSend?.queued ? "messages queued" : latestUpdatedAt ? `Updated ${formatCompactDate(latestUpdatedAt)}` : "no active queue"}
              icon={displayedSend?.queued ? Activity : Clock3}
              tone={displayedSend?.queued ? "attention" : "default"}
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      {displayedSend && (
        <div
          role="status"
          aria-live="polite"
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

      {error && (
        <WorkspaceErrorNotice>
          WhatsApp broadcast groups could not be refreshed. Existing delivery history and queued-batch tracking remain unchanged.
        </WorkspaceErrorNotice>
      )}

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="whatsapp-broadcast-groups-heading"
      >
        <div className="border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
            Recipient operations
          </p>
          <h2 id="whatsapp-broadcast-groups-heading" className="mt-0.5 font-semibold text-slate-950">
            Broadcast groups
          </h2>
        </div>
        <WorkspaceToolbar
          query={groupQuery}
          onQueryChange={setGroupQuery}
          searchLabel="Search WhatsApp broadcast groups"
          placeholder="Search broadcast groups"
          resultLabel={`${filteredGroups.length.toLocaleString()} groups`}
        />

        {isLoading ? (
          <div className="space-y-3 p-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-16 w-full rounded-lg" />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <WorkspaceEmptyState
            title="Create the first WhatsApp broadcast group"
            description="Add recipients manually or upload an Excel file, then preview approved trip messages before sending them individually."
            action={(
              <Button type="button" onClick={() => setShowCreate(true)}>
                <Plus className="h-4 w-4" aria-hidden="true" />
                Create Broadcast
              </Button>
            )}
          />
        ) : filteredGroups.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No broadcast groups match this search"
            description="Search by the broadcast group name or clear the search to return to every recipient list."
          />
        ) : (
          <>
            <div className="divide-y divide-slate-100 md:hidden">
              {filteredGroups.map((group) => (
                <article
                  key={group.id}
                  className="px-4 py-4"
                  style={{ contentVisibility: "auto", containIntrinsicSize: "0 180px" }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="font-semibold text-slate-950">{group.name}</h3>
                      <p className="mt-1 text-xs text-slate-500">
                        Updated {formatDateTime(group.updated_at)}
                      </p>
                    </div>
                    {renderGroupActionMenu(group, "mobile")}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-3 border-t border-slate-100 pt-3 text-sm">
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                        Total contacts
                      </p>
                      <p className="mt-1 font-semibold tabular-nums text-slate-900">
                        {group.total_contact_count}
                      </p>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                        Eligible
                      </p>
                      <p className="mt-1 font-semibold tabular-nums text-emerald-700">
                        {group.recipient_count.toLocaleString()}
                      </p>
                    </div>
                  </div>
                  {group.total_contact_count !== group.recipient_count && (
                    <p className="mt-3 text-xs font-medium text-amber-700">
                      {(group.total_contact_count - group.recipient_count).toLocaleString()} contact exceptions require review
                    </p>
                  )}
                </article>
              ))}
            </div>

            <div className="hidden overflow-x-auto md:block">
              <table className="w-full min-w-[760px] text-left text-sm">
                <caption className="sr-only">WhatsApp broadcast groups and recipient readiness</caption>
                <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
                  <tr>
                    <th scope="col" className="px-5 py-3.5">Group Name</th>
                    <th scope="col" className="px-5 py-3.5">Recipient readiness</th>
                    <th scope="col" className="px-5 py-3.5">Updated</th>
                    <th scope="col" className="px-5 py-3.5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filteredGroups.map((group) => (
                    <tr
                      key={group.id}
                      className="transition-colors hover:bg-slate-50/70"
                    >
                      <td className="px-5 py-4">
                        <div className="font-medium text-slate-900">
                          {group.name}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Used in approved trip wording
                        </div>
                      </td>
                      <td className="px-5 py-4 text-slate-700">
                        <span className="inline-flex items-center gap-1.5 font-medium">
                          <Users className="h-4 w-4 text-slate-400" />
                          {group.total_contact_count} total contacts
                        </span>
                        <p className="mt-1 text-xs text-emerald-700">
                          {group.recipient_count.toLocaleString()} eligible to receive
                        </p>
                        {group.total_contact_count !== group.recipient_count && (
                          <p className="mt-1 text-xs text-amber-700">
                            {(group.total_contact_count - group.recipient_count).toLocaleString()} contact exceptions
                          </p>
                        )}
                      </td>
                      <td className="px-5 py-4 text-slate-600">
                        {formatDateTime(group.updated_at)}
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex justify-end">
                          {renderGroupActionMenu(group, "desktop")}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

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
          isSending={
            sendWelcome.isPending ||
            sendPassportLink.isPending ||
            sendReminder.isPending
          }
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
                : messageTarget.messageType === "reminder"
                  ? await sendReminder.mutateAsync({
                      groupId: messageTarget.group.id,
                      messageContent,
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
                groupId: messageTarget.group.id,
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
  onReminder,
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
  onReminder: () => void;
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
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={isSending || group.recipient_count === 0}
              title={
                group.recipient_count === 0
                  ? "Add a valid recipient before sending"
                  : undefined
              }
              onClick={onReminder}
            >
              <Send className="h-4 w-4" />
              Send Reminder
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
