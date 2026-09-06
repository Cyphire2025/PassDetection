"use client";

import {
  Activity,
  CheckCircle2,
  Clock3,
  MessageCircle,
  MoreVertical,
  Plus,
  Send,
  Trash2,
  Users,
} from "lucide-react";
import dynamic from "next/dynamic";
import {
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
} from "../api/whatsapp.api";
import {
  useCreateWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useSendWhatsAppPassportLink,
  useSendWhatsAppReminder,
  useSendWhatsAppWelcome,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";
import { formatMessageType } from "../utils/message-types";
import {
  WhatsAppActivityInline,
  useWhatsAppActivityTracker,
} from "./whatsapp-activity-tracker";

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
  const { activities, registerActivity } = useWhatsAppActivityTracker();
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
  const currentBatchQueued = activities.reduce(
    (total, activity) =>
      activity.kind === "broadcast" ? total + activity.queued : total,
    0,
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
        title="WhatsApp"
        description="Manage recipient lists, preview trip messages, and track delivery."
        icon={MessageCircle}
        accent="emerald"
        context={(
          <WorkspaceHeaderContext icon={Users}>{totalEligibleRecipients.toLocaleString()} eligible recipients</WorkspaceHeaderContext>
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
              value={currentBatchQueued.toLocaleString()}
              helper={currentBatchQueued ? "messages queued" : latestUpdatedAt ? `Updated ${formatCompactDate(latestUpdatedAt)}` : "no active queue"}
              icon={currentBatchQueued ? Activity : Clock3}
              tone={currentBatchQueued ? "attention" : "default"}
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <WhatsAppActivityInline />

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
            const startedAt = Date.now();
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
            if (result.batch_id) {
              registerActivity({
                id: result.batch_id,
                kind: "broadcast",
                messageType: messageTarget.messageType,
                startedAt,
                title: `${formatMessageType(messageTarget.messageType)} broadcast`,
                contextLabel: messageTarget.group.name,
                sourceGroupId: messageTarget.group.id,
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
