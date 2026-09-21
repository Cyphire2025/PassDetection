"use client";

import {
  Activity,
  Archive,
  CheckCircle2,
  Clock3,
  MessageCircle,
  MoreVertical,
  Plus,
  RotateCcw,
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
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
  WorkspaceToolbar,
} from "@/components/shared/workspace-ui";
import { WhatsAppBroadcastList } from "./whatsapp-broadcast-list";
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
  useArchiveWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useRestoreWhatsAppGroup,
  useSendWhatsAppPassportLink,
  useSendWhatsAppReminder,
  useSendWhatsAppGroupInvite,
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
  const { data: archivedGroups = [], isLoading: isLoadingArchived, error: archivedError } = useWhatsAppGroups(true);
  const createGroup = useCreateWhatsAppGroup();
  const archiveGroup = useArchiveWhatsAppGroup();
  const restoreGroup = useRestoreWhatsAppGroup();
  const deleteGroup = useDeleteWhatsAppGroup();
  const sendWelcome = useSendWhatsAppWelcome();
  const sendPassportLink = useSendWhatsAppPassportLink();
  const sendReminder = useSendWhatsAppReminder();
  const sendGroupInvite = useSendWhatsAppGroupInvite();
  const [isArchiveExpanded, setIsArchiveExpanded] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [groupQuery, setGroupQuery] = useState("");
  const deferredGroupQuery = useDeferredValue(groupQuery);
  const [openMenuKey, setOpenMenuKey] = useState<string | null>(null);
  const [recipientListGroup, setRecipientListGroup] =
    useState<WhatsAppBroadcastGroup | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<WhatsAppBroadcastGroup | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<WhatsAppBroadcastGroup | null>(null);
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
  const filteredArchivedGroups = useMemo(() => {
    const normalized = deferredGroupQuery.trim().toLocaleLowerCase();
    return archivedGroups.filter((group) => group.name.toLocaleLowerCase().includes(normalized));
  }, [deferredGroupQuery, archivedGroups]);
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
    if (group.is_archived) return;
    setOpenMenuKey(null);
    setMessageTarget({ group, messageType });
  };
  const isSendingAnyMessage =
    sendWelcome.isPending || sendPassportLink.isPending || sendReminder.isPending || sendGroupInvite.isPending;
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
        isMutating={archiveGroup.isPending || restoreGroup.isPending || deleteGroup.isPending}
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
        onGroupInvite={() => openMessagePreview(group, "group_invite")}
        onArchive={() => {
          setActionError(null);
          setOpenMenuKey(null);
          setArchiveTarget(group);
        }}
        onRestore={() => {
          setActionError(null);
          setOpenMenuKey(null);
          restoreGroup.mutate(group.id, {
            onError: (restoreError) => setActionError(readErrorMessage(restoreError, "Could not restore this WhatsApp broadcast.")),
          });
        }}
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
          <><WorkspaceHeaderContext icon={Users}>{totalEligibleRecipients.toLocaleString()} eligible recipients</WorkspaceHeaderContext>
          <WorkspaceHeaderContext icon={Archive}>{archivedGroups.length.toLocaleString()} archived</WorkspaceHeaderContext></>
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
              label="Active broadcasts"
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

      {(error || archivedError) && (
        <WorkspaceErrorNotice>
          WhatsApp broadcast groups could not be refreshed. Existing delivery history and queued-batch tracking remain unchanged.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceToolbar
        query={groupQuery}
        onQueryChange={(value) => { setGroupQuery(value); setOpenMenuKey(null); }}
        searchLabel="Search WhatsApp broadcast groups"
        placeholder="Search active and archived broadcasts"
        resultLabel={`${filteredGroups.length.toLocaleString()} active · ${filteredArchivedGroups.length.toLocaleString()} archived`}
      />
      <WhatsAppBroadcastList
        key={`active:${deferredGroupQuery}`}
        groups={filteredGroups}
        totalCount={groups.length}
        isLoading={isLoading}
        renderActions={renderGroupActionMenu}
        onCreate={() => setShowCreate(true)}
      />
      <WhatsAppBroadcastList
        key={`archived:${deferredGroupQuery}`}
        archived
        expanded={isArchiveExpanded}
        onToggle={() => { setIsArchiveExpanded((current) => !current); setOpenMenuKey(null); }}
        groups={filteredArchivedGroups}
        totalCount={archivedGroups.length}
        isLoading={isLoadingArchived}
        renderActions={renderGroupActionMenu}
        onCreate={() => setShowCreate(true)}
      />
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
            sendReminder.isPending || sendGroupInvite.isPending
          }
          onClose={() => setMessageTarget(null)}
          onSend={async ({
            passportIntro,
            passportLink,
            groupInviteLink,
            messageContent,
            headerImage,
            headerImageId,
            recipientIds,
            supportContactIds,
            reminderAudience,
            reminderAudienceClientGroupId,
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
                      audience: reminderAudience ?? "all",
                      audienceClientGroupId: reminderAudienceClientGroupId ?? null,
                    })
                  : messageTarget.messageType === "group_invite"
                    ? await sendGroupInvite.mutateAsync({ groupId: messageTarget.group.id, messageContent, groupInviteLink: groupInviteLink ?? "", recipientIds, image: headerImage, headerImageId })
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
        isOpen={Boolean(archiveTarget)}
        title="Archive WhatsApp broadcast?"
        description={`${archiveTarget?.name ?? "This broadcast"} will move out of active work. Its recipients, linked groups, and delivery history will be retained. Restore it to edit recipients or send messages again. Wait for queued or processing deliveries to finish and resolve any unknown delivery status before archiving.`}
        confirmLabel="Archive Broadcast"
        isLoading={archiveGroup.isPending}
        onClose={() => setArchiveTarget(null)}
        onConfirm={() => {
          if (!archiveTarget) return;
          archiveGroup.mutate(archiveTarget.id, {
            onSuccess: () => setArchiveTarget(null),
            onError: (archiveError) => {
              setActionError(readErrorMessage(archiveError, "Could not archive this WhatsApp broadcast."));
              setArchiveTarget(null);
            },
          });
        }}
      />
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
  isMutating,
  onOpen,
  onClose,
  onRecipients,
  onWelcome,
  onPassportLink,
  onReminder,
  onGroupInvite,
  onArchive,
  onRestore,
  onDelete,
}: {
  group: WhatsAppBroadcastGroup;
  isOpen: boolean;
  isSending: boolean;
  isMutating: boolean;
  onOpen: () => void;
  onClose: () => void;
  onRecipients: () => void;
  onWelcome: () => void;
  onPassportLink: () => void;
  onReminder: () => void;
  onGroupInvite: () => void;
  onArchive: () => void;
  onRestore: () => void;
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
            const menuHeight = group.is_archived ? 152 : 296;
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
            {!group.is_archived && <>
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
            <button type="button" className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" disabled={isSending || group.recipient_count === 0} title={group.recipient_count === 0 ? "Add a valid recipient before sending" : undefined} onClick={onGroupInvite}>
              <Send className="h-4 w-4" /> Send group invite
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 border-t border-slate-100 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              disabled={isSending || isMutating}
              onClick={onArchive}
            >
              <Archive className="h-4 w-4" /> Archive Broadcast
            </button>
            </>}
            {group.is_archived && <>
            <button
              type="button"
              className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50"
              disabled={isMutating}
              onClick={onRestore}
            >
              <RotateCcw className="h-4 w-4" /> Restore Broadcast
            </button>
            <button
              type="button"
              className="flex w-full items-center gap-2 border-t border-slate-100 px-4 py-3 text-left text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
              disabled={isSending || isMutating}
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" />
              Delete Broadcast
            </button>
            </>}
          </div>,
          document.body,
        )}
    </div>
  );
}
