"use client";

import { Archive, Check, CheckCircle2, Clock, Copy, Link2, Pencil, RotateCcw, Trash2, XCircle } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { ConfirmDialog, TextInputDialog } from "@/components/ui";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { getPassportUploadTargets } from "@/lib/utils/public-url";
import type { UploadLinkResponse } from "../api/upload-links.api";
import {
  useDeleteUploadLink,
  usePermanentlyDeleteUploadLink,
  useRestoreUploadLink,
  useRevokeUploadLink,
  useUpdateUploadLink,
  useUploadLinks,
} from "../hooks/use-upload-links";
import { CreateUploadLinkModal } from "./create-upload-link-modal";

export function UploadLinkList() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [copiedLinkKey, setCopiedLinkKey] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    description: string;
    confirmLabel: string;
    variant?: "primary" | "danger";
    onConfirm: () => void;
  } | null>(null);
  const [renameTarget, setRenameTarget] = useState<UploadLinkResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<UploadLinkResponse | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const { data: activeLinks = [], isLoading: isLoadingActive } = useUploadLinks();
  const { data: archivedLinks = [], isLoading: isLoadingArchived } = useUploadLinks("archived");
  const { mutate: closeLink, isPending: isClosing } = useRevokeUploadLink();
  const { mutate: archiveLink, isPending: isArchiving } = useDeleteUploadLink();
  const { mutate: restoreLink, isPending: isRestoring } = useRestoreUploadLink();
  const { mutate: renameLink, isPending: isRenaming } = useUpdateUploadLink();
  const { mutate: permanentlyDeleteLink, isPending: isPermanentlyDeleting } = usePermanentlyDeleteUploadLink();

  const copyUploadLink = async (linkId: string, targetKey: string, url: string) => {
    try {
      await copyTextToClipboard(url);
      setCopyError(null);
      setCopiedLinkKey(`${linkId}:${targetKey}`);
      window.setTimeout(() => {
        setCopiedLinkKey((current) => current === `${linkId}:${targetKey}` ? null : current);
      }, 2000);
    } catch {
      setCopiedLinkKey(null);
      setCopyError("Could not copy the link. Check your browser clipboard permission and try again.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Upload Links"
        description="Create client group links and keep archived groups out of active work."
        actions={(
          <Button size="sm" onClick={() => setIsModalOpen(true)}>
            Create Link
          </Button>
        )}
      />

      <CreateUploadLinkModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />

      {copyError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {copyError}
        </div>
      )}

      {isLoadingActive ? (
        <LoadingRows />
      ) : activeLinks.length === 0 ? (
        <EmptyState
          icon={<Link2 className="h-5 w-5" />}
          title="No active upload links"
          description="Create a secure group link to collect passport images from clients."
          action={{ label: "Create link", onClick: () => setIsModalOpen(true) }}
        />
      ) : (
        <UploadLinkTable
          links={activeLinks}
          copiedLinkKey={copiedLinkKey}
          onCopy={copyUploadLink}
          onClose={(id) => {
            setConfirmAction({
              title: "Close Group",
              description: "Clients will no longer be able to upload passports through this group link. Existing submissions remain available for review.",
              confirmLabel: "Close Group",
              onConfirm: () => closeLink(id, { onSuccess: () => setConfirmAction(null) }),
            });
          }}
          onArchive={(id) => {
            setConfirmAction({
              title: "Archive Group",
              description: "This group will be removed from active work. Existing passport records and uploaded images will be retained.",
              confirmLabel: "Archive Group",
              onConfirm: () => archiveLink(id, { onSuccess: () => setConfirmAction(null) }),
            });
          }}
          onRename={(link) => {
            setRenameTarget(link);
            setRenameValue(link.name);
          }}
          isMutating={isClosing || isArchiving || isRenaming}
        />
      )}

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-slate-900">Archived</h2>
            <p className="text-sm text-slate-500">Groups removed from active passport queues.</p>
          </div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            {archivedLinks.length}
          </span>
        </div>

        {isLoadingArchived ? (
          <div className="p-6"><LoadingRows /></div>
        ) : archivedLinks.length === 0 ? (
          <div className="px-6 py-8 text-sm text-slate-500">No archived groups.</div>
        ) : (
          <UploadLinkTable
            links={archivedLinks}
            copiedLinkKey={copiedLinkKey}
            onCopy={copyUploadLink}
            onRestore={(id) => restoreLink(id)}
            onRename={(link) => {
              setRenameTarget(link);
              setRenameValue(link.name);
            }}
            onPermanentDelete={(id) => {
              setDeleteTarget(archivedLinks.find((link) => link.id === id) ?? null);
            }}
            isMutating={isRestoring || isRenaming || isPermanentlyDeleting}
            compact
          />
        )}
      </section>

      <ConfirmDialog
        isOpen={Boolean(confirmAction)}
        title={confirmAction?.title ?? ""}
        description={confirmAction?.description ?? ""}
        confirmLabel={confirmAction?.confirmLabel ?? "Confirm"}
        variant={confirmAction?.variant}
        isLoading={isClosing || isArchiving || isRestoring || isPermanentlyDeleting}
        onClose={() => setConfirmAction(null)}
        onConfirm={() => confirmAction?.onConfirm()}
      />
      <TextInputDialog
        isOpen={Boolean(renameTarget)}
        title="Rename Group"
        description="Update the group name shown in upload links, passport queues, and exports."
        label="Group name"
        value={renameValue}
        confirmLabel="Save Name"
        isLoading={isRenaming}
        onValueChange={setRenameValue}
        onClose={() => setRenameTarget(null)}
        onConfirm={() => {
          if (!renameTarget) return;
          const nextName = renameValue.trim();
          if (!nextName || nextName === renameTarget.name) {
            setRenameTarget(null);
            return;
          }
          renameLink(
            { id: renameTarget.id, name: nextName },
            { onSuccess: () => setRenameTarget(null) },
          );
        }}
      />
      <GroupDeleteRetentionDialog
        group={deleteTarget}
        isLoading={isPermanentlyDeleting}
        onClose={() => setDeleteTarget(null)}
        onKeepData={() => {
          if (!deleteTarget) return;
          permanentlyDeleteLink(
            { id: deleteTarget.id, retainRecords: true },
            { onSuccess: () => setDeleteTarget(null) },
          );
        }}
        onDeleteData={() => {
          if (!deleteTarget) return;
          permanentlyDeleteLink(
            { id: deleteTarget.id, retainRecords: false },
            { onSuccess: () => setDeleteTarget(null) },
          );
        }}
      />
    </div>
  );
}

type UploadLinkTableProps = {
  links: UploadLinkResponse[];
  copiedLinkKey: string | null;
  onCopy: (linkId: string, targetKey: string, url: string) => void;
  onClose?: (id: string) => void;
  onArchive?: (id: string) => void;
  onRestore?: (id: string) => void;
  onRename?: (link: UploadLinkResponse) => void;
  onPermanentDelete?: (id: string) => void;
  isMutating?: boolean;
  compact?: boolean;
};

function UploadLinkTable({
  links,
  copiedLinkKey,
  onCopy,
  onClose,
  onArchive,
  onRestore,
  onRename,
  onPermanentDelete,
  isMutating = false,
  compact = false,
}: UploadLinkTableProps) {
  return (
    <div className={compact ? "overflow-x-auto" : "overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"}>
      <table className="w-full text-left text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
          <tr>
            <th className="px-6 py-4">Group Name</th>
            <th className="px-6 py-4">Status</th>
            <th className="px-6 py-4">Created</th>
            <th className="px-6 py-4">Closed</th>
            <th className="px-6 py-4 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {links.map((link) => {
            const uploadTargets = getPassportUploadTargets(link.token);
            return (
              <tr key={link.id} className="transition-colors hover:bg-slate-50/50">
                <td className="px-6 py-4">
                  <div className="font-medium text-slate-900">{link.name}</div>
                </td>
                <td className="px-6 py-4"><StatusPill status={link.status} /></td>
                <td className="px-6 py-4 text-slate-600">{new Date(link.created_at).toLocaleDateString()}</td>
                <td className="px-6 py-4 text-slate-600">
                  {link.closed_at ? new Date(link.closed_at).toLocaleDateString() : "-"}
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    {link.status === "active" && uploadTargets.map((target) => {
                      const copyStateKey = `${link.id}:${target.key}`;
                      return (
                        <Button
                          key={target.key}
                          type="button"
                          variant="secondary"
                          size="sm"
                          onClick={() => onCopy(link.id, target.key, target.url)}
                          aria-label={`Copy ${target.label.toLowerCase()} upload link for ${link.name}`}
                        >
                          {copiedLinkKey === copyStateKey ? (
                            <><Check className="h-3.5 w-3.5 text-green-600" /> Copied</>
                          ) : (
                            <><Copy className="h-3.5 w-3.5" /> {target.label}</>
                          )}
                        </Button>
                      );
                    })}
                    {link.status === "active" && onClose && (
                      <Button type="button" variant="outline" size="sm" onClick={() => onClose(link.id)} disabled={isMutating}>
                        <XCircle className="h-3.5 w-3.5" /> Close
                      </Button>
                    )}
                    {onRename && (
                      <Button type="button" variant="secondary" size="sm" onClick={() => onRename(link)} disabled={isMutating}>
                        <Pencil className="h-3.5 w-3.5" /> Rename
                      </Button>
                    )}
                    {link.status !== "archived" && onArchive && (
                      <Button type="button" variant="ghost" size="sm" onClick={() => onArchive(link.id)} disabled={isMutating}>
                        <Archive className="h-3.5 w-3.5" /> Archive
                      </Button>
                    )}
                    {link.status === "archived" && onRestore && (
                      <Button type="button" variant="secondary" size="sm" onClick={() => onRestore(link.id)} disabled={isMutating}>
                        <RotateCcw className="h-3.5 w-3.5" /> Restore
                      </Button>
                    )}
                    {link.status === "archived" && onPermanentDelete && (
                      <Button type="button" variant="danger" size="sm" onClick={() => onPermanentDelete(link.id)} disabled={isMutating}>
                        <Trash2 className="h-3.5 w-3.5" /> Delete
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatusPill({ status }: { status: UploadLinkResponse["status"] }) {
  if (status === "active") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
        <Clock className="h-3.5 w-3.5" /> Active
      </span>
    );
  }
  if (status === "closed") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700">
        <CheckCircle2 className="h-3.5 w-3.5" /> Closed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">
      <Archive className="h-3.5 w-3.5" /> Archived
    </span>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-12 rounded-lg bg-slate-100" />
      <div className="h-12 rounded-lg bg-slate-100" />
      <div className="h-12 rounded-lg bg-slate-100" />
    </div>
  );
}

function GroupDeleteRetentionDialog({
  group,
  isLoading,
  onClose,
  onKeepData,
  onDeleteData,
}: {
  group: UploadLinkResponse | null;
  isLoading: boolean;
  onClose: () => void;
  onKeepData: () => void;
  onDeleteData: () => void;
}) {
  if (!group) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="border-b border-slate-100 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Delete Archived Group</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Choose how passport records for <span className="font-semibold text-slate-900">{group.name}</span> should be handled.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              aria-label="Close dialog"
            >
              <XCircle className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="grid gap-4 p-6 md:grid-cols-2">
          <button
            type="button"
            disabled={isLoading}
            onClick={onKeepData}
            className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-left transition hover:border-blue-300 hover:bg-blue-100 disabled:opacity-60"
          >
            <div className="text-base font-semibold text-blue-950">Keep passport records</div>
            <p className="mt-2 text-sm leading-6 text-blue-800">
              Move this group to Old Data. Managers will no longer see it, but Super Admin can access the saved group folder and its passport records later.
            </p>
          </button>

          <button
            type="button"
            disabled={isLoading}
            onClick={onDeleteData}
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-left transition hover:border-red-300 hover:bg-red-100 disabled:opacity-60"
          >
            <div className="text-base font-semibold text-red-950">Delete passport records</div>
            <p className="mt-2 text-sm leading-6 text-red-800">
              Permanently remove uploaded passport files and extracted records. The historical passport count for this group will still remain in total submissions.
            </p>
          </button>
        </div>

        <div className="flex justify-end border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
