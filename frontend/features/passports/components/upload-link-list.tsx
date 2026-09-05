"use client";

import dynamic from "next/dynamic";
import {
  Archive,
  CalendarDays,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Link2,
  Pencil,
  RotateCcw,
  Trash2,
  X,
  XCircle,
} from "lucide-react";
import { useDeferredValue, useMemo, useRef, useState } from "react";
import {
  WorkspaceEmptyState,
  WorkspaceErrorNotice,
  WorkspaceHeaderContext,
  WorkspacePageHeader,
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
  WorkspaceToolbar,
} from "@/components/shared/workspace-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { getPassportUploadTargets } from "@/lib/utils/public-url";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type {
  UploadLinkResponse,
} from "../api/upload-links.api";
import {
  useDeleteUploadLink,
  usePermanentlyDeleteUploadLink,
  useRestoreUploadLink,
  useRevokeUploadLink,
  useUpdateUploadLink,
  useUploadLinks,
} from "../hooks/use-upload-links";
import {
  getUploadLinkSettings,
  getUploadLinkSettingsError,
  UploadLinkSettings,
  type UploadLinkSettingsValue,
} from "./upload-link-settings";

const loadCreateUploadLinkModal = () =>
  import("./create-upload-link-modal");

const CreateUploadLinkModal = dynamic(
  () => import("./create-upload-link-modal").then((module) => module.CreateUploadLinkModal),
  { loading: () => null },
);

export function UploadLinkList() {
  const role = useAuthStore(selectUserRole);
  const canPermanentlyDelete = role !== "agency_staff";
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
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
  const [editSettings, setEditSettings] = useState(() => getUploadLinkSettings({}));
  const {
    data: activeLinks = [],
    isLoading: isLoadingActive,
    error: activeLinksError,
  } = useUploadLinks();
  const {
    data: archivedLinks = [],
    isLoading: isLoadingArchived,
    error: archivedLinksError,
  } = useUploadLinks("archived");
  const { mutate: closeLink, isPending: isClosing } = useRevokeUploadLink();
  const { mutate: archiveLink, isPending: isArchiving } = useDeleteUploadLink();
  const { mutate: restoreLink, isPending: isRestoring } = useRestoreUploadLink();
  const { mutate: renameLink, isPending: isRenaming } = useUpdateUploadLink();
  const { mutate: permanentlyDeleteLink, isPending: isPermanentlyDeleting } = usePermanentlyDeleteUploadLink();
  const filteredActiveLinks = useMemo(
    () => filterUploadLinks(activeLinks, deferredQuery),
    [activeLinks, deferredQuery],
  );
  const filteredArchivedLinks = useMemo(
    () => filterUploadLinks(archivedLinks, deferredQuery),
    [archivedLinks, deferredQuery],
  );
  const activeCount = activeLinks.filter((link) => link.status === "active").length;
  const closedCount = activeLinks.filter((link) => link.status === "closed").length;
  const datedCount = [...activeLinks, ...archivedLinks].filter((link) => link.travel_date).length;

  const openGroupEditor = (link: UploadLinkResponse) => {
    setRenameTarget(link);
    setRenameValue(link.name);
    setEditSettings(getUploadLinkSettings(link));
  };

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
    <div className="flex flex-col gap-5">
      <WorkspacePageHeader
        title="Group Links"
        description="Create passport upload links and manage active, closed, and archived groups."
        icon={Link2}
        accent="emerald"
        context={(
          <>
            <WorkspaceHeaderContext icon={Link2}>
              {activeCount.toLocaleString()} collecting now
            </WorkspaceHeaderContext>
            <WorkspaceHeaderContext icon={Archive}>
              {archivedLinks.length.toLocaleString()} archived
            </WorkspaceHeaderContext>
          </>
        )}
        actions={(
          <Button
            onClick={() => setIsModalOpen(true)}
            onMouseEnter={() => void loadCreateUploadLinkModal()}
            onFocus={() => void loadCreateUploadLinkModal()}
            onPointerDown={() => void loadCreateUploadLinkModal()}
            className="bg-white text-[#123f73] shadow-sm hover:bg-emerald-50 active:bg-emerald-100"
          >
            <Link2 className="h-4 w-4" aria-hidden="true" />
            Create Group Link
          </Button>
        )}
      />

      {isModalOpen && (
        <CreateUploadLinkModal isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
      )}

      {copyError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {copyError}
        </div>
      )}
      {(activeLinksError || archivedLinksError) && (
        <WorkspaceErrorNotice>
          One or more Group Link lists could not be refreshed. Existing links and actions remain unchanged.
        </WorkspaceErrorNotice>
      )}

      <WorkspaceSummaryStrip label="Group Link lifecycle summary">
        {isLoadingActive || isLoadingArchived ? (
          Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-[72px] animate-pulse bg-slate-100" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Active links"
              value={activeCount.toLocaleString()}
              helper="accepting uploads"
              icon={Link2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Closed groups"
              value={closedCount.toLocaleString()}
              helper="intake stopped"
              icon={CheckCircle2}
            />
            <WorkspaceSummaryItem
              label="Archived"
              value={archivedLinks.length.toLocaleString()}
              helper="retained history"
              icon={Archive}
            />
            <WorkspaceSummaryItem
              label="Travel date set"
              value={datedCount.toLocaleString()}
              helper="configured groups"
              icon={CalendarDays}
              tone="info"
            />
          </>
        )}
      </WorkspaceSummaryStrip>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="group-links-heading"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <div>

            <h2 id="group-links-heading" className="mt-0.5 font-semibold text-slate-950">
              Live and closed group links
            </h2>
          </div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            {activeLinks.length.toLocaleString()}
          </span>
        </div>

        <WorkspaceToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search Group Links"
          placeholder="Search group, destination, package, or departure city"
          resultLabel={`${filteredActiveLinks.length.toLocaleString()} active or closed`}
        />

        {isLoadingActive ? (
          <div className="p-5"><LoadingRows /></div>
        ) : activeLinks.length === 0 ? (
          <WorkspaceEmptyState
            title="No Group Links are collecting details"
            description="Create a Group Link to collect passport images and traveller details."
            action={(
              <Button type="button" onClick={() => setIsModalOpen(true)}>
                <Link2 className="h-4 w-4" aria-hidden="true" />
                Create Group Link
              </Button>
            )}
          />
        ) : filteredActiveLinks.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No live or closed links match this search"
            description="Search by group, destination, package, or departure city, or clear the search to restore the full list."
          />
        ) : (
          <UploadLinkTable
            caption="Live and closed Group Links"
            links={filteredActiveLinks}
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
            onRename={openGroupEditor}
            isMutating={isClosing || isArchiving || isRenaming}
            compact
          />
        )}
      </section>

      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="archived-group-links-heading"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <div>

            <h2 id="archived-group-links-heading" className="mt-0.5 font-semibold text-slate-950">
              Archived groups
            </h2>
            <p className="mt-1 text-sm text-slate-500">Groups removed from active passport queues.</p>
          </div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            {archivedLinks.length.toLocaleString()}
          </span>
        </div>

        {isLoadingArchived ? (
          <div className="p-5"><LoadingRows /></div>
        ) : archivedLinks.length === 0 ? (
          <WorkspaceEmptyState
            title="No archived Group Links"
            description="Groups moved out of active work will remain available here according to their retention choice."
          />
        ) : filteredArchivedLinks.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No archived groups match this search"
            description="Clear the shared Group Link search to restore archived history."
          />
        ) : (
          <UploadLinkTable
            caption="Archived Group Links"
            links={filteredArchivedLinks}
            copiedLinkKey={copiedLinkKey}
            onCopy={copyUploadLink}
            onRestore={(id) => restoreLink(id)}
            onRename={openGroupEditor}
            onPermanentDelete={(id) => {
              setDeleteTarget(archivedLinks.find((link) => link.id === id) ?? null);
            }}
            canPermanentlyDelete={canPermanentlyDelete}
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
      <EditGroupDialog
        group={renameTarget}
        name={renameValue}
        settings={editSettings}
        isLoading={isRenaming}
        onNameChange={setRenameValue}
        onSettingsChange={(patch) => setEditSettings((current) => ({ ...current, ...patch }))}
        onClose={() => setRenameTarget(null)}
        onConfirm={() => {
          if (!renameTarget) return;
          const nextName = renameValue.trim();
          if (getUploadLinkSettingsError(editSettings)) return;
          const hasChanges = nextName !== renameTarget.name
            || JSON.stringify(editSettings) !== JSON.stringify(getUploadLinkSettings(renameTarget));
          if (!nextName || !hasChanges) {
            setRenameTarget(null);
            return;
          }
          renameLink(
            {
              id: renameTarget.id,
              name: nextName,
              destination: renameTarget.destination,
              travel_date: renameTarget.travel_date,
              return_date: renameTarget.return_date,
              package_name: renameTarget.package_name,
              timezone: renameTarget.timezone,
              ...editSettings,
              departure_cities: editSettings.nearest_international_airport_enabled ? editSettings.departure_cities : [],
              notes: renameTarget.notes,
            },
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

function EditGroupDialog({
  group,
  name,
  settings,
  isLoading,
  onNameChange,
  onSettingsChange,
  onConfirm,
  onClose,
}: {
  group: UploadLinkResponse | null;
  name: string;
  settings: UploadLinkSettingsValue;
  isLoading: boolean;
  onNameChange: (value: string) => void;
  onSettingsChange: (patch: Partial<UploadLinkSettingsValue>) => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: Boolean(group),
    canClose: !isLoading,
    onClose,
  });
  if (!group) return null;
  const settingsError = getUploadLinkSettingsError(settings);

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-passport-group-title"
      onKeyDown={handleDialogKeyDown}
    >
      <form
        className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
        onSubmit={(event) => {
          event.preventDefault();
          if (!isLoading && !settingsError && name.trim()) onConfirm();
        }}
      >
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
          <div>
            <h2 id="edit-passport-group-title" className="text-lg font-semibold text-slate-900">
              Edit Group
            </h2>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Update the group name and traveller passport-capture requirements.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isLoading}
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Close edit group dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="max-h-[calc(90vh-9rem)] space-y-4 overflow-y-auto px-6 py-5">
          <Input
            label="Group name"
            value={name}
            maxLength={100}
            required
            data-dialog-initial-focus
            disabled={isLoading}
            onChange={(event) => onNameChange(event.target.value)}
          />
          <UploadLinkSettings value={settings} onChange={onSettingsChange} disabled={isLoading} error={settingsError} />
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            type="submit"
            isLoading={isLoading}
            disabled={!name.trim() || Boolean(settingsError) || isLoading}
          >
            Save changes
          </Button>
        </div>
      </form>
    </div>
  );
}

type UploadLinkTableProps = {
  caption: string;
  links: UploadLinkResponse[];
  copiedLinkKey: string | null;
  onCopy: (linkId: string, targetKey: string, url: string) => void;
  onClose?: (id: string) => void;
  onArchive?: (id: string) => void;
  onRestore?: (id: string) => void;
  onRename?: (link: UploadLinkResponse) => void;
  onPermanentDelete?: (id: string) => void;
  canPermanentlyDelete?: boolean;
  isMutating?: boolean;
  compact?: boolean;
};

function UploadLinkTable({
  caption,
  links,
  copiedLinkKey,
  onCopy,
  onClose,
  onArchive,
  onRestore,
  onRename,
  onPermanentDelete,
  canPermanentlyDelete = true,
  isMutating = false,
  compact = false,
}: UploadLinkTableProps) {
  const renderActions = (
    link: UploadLinkResponse,
    align: "start" | "end",
  ) => {
    const uploadTargets = getPassportUploadTargets(link.token);
    return (
      <div
        className={`flex flex-wrap items-center gap-2 ${
          align === "end" ? "justify-end" : "justify-start"
        }`}
      >
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
            <Pencil className="h-3.5 w-3.5" /> Edit
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
        {canPermanentlyDelete && link.status === "archived" && onPermanentDelete && (
          <Button type="button" variant="danger" size="sm" onClick={() => onPermanentDelete(link.id)} disabled={isMutating}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </Button>
        )}
      </div>
    );
  };

  return (
    <div className={compact ? "" : "overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"}>
      <div className="divide-y divide-slate-100 md:hidden">
        {links.map((link) => (
          <article
            key={link.id}
            className="px-4 py-4"
            style={{ contentVisibility: "auto", containIntrinsicSize: "0 240px" }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="font-semibold text-slate-950">{link.name}</h3>
                {link.destination && (
                  <p className="mt-1 truncate text-xs text-slate-500">{link.destination}</p>
                )}
              </div>
              <StatusPill status={link.status} />
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3 border-y border-slate-100 py-3 text-sm">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Created</dt>
                <dd className="mt-1 font-medium text-slate-800">
                  {new Date(link.created_at).toLocaleDateString()}
                </dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Closed</dt>
                <dd className="mt-1 font-medium text-slate-800">
                  {link.closed_at ? new Date(link.closed_at).toLocaleDateString() : "Not closed"}
                </dd>
              </div>
            </dl>
            <div className="mt-3">{renderActions(link, "start")}</div>
          </article>
        ))}
      </div>

      <div className="hidden overflow-x-auto md:block">
        <table className="w-full min-w-[980px] text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
            <tr>
              <th scope="col" className="px-5 py-3.5">Group Name</th>
              <th scope="col" className="px-5 py-3.5">Status</th>
              <th scope="col" className="px-5 py-3.5">Created</th>
              <th scope="col" className="px-5 py-3.5">Closed</th>
              <th scope="col" className="px-5 py-3.5 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {links.map((link) => (
              <tr key={link.id} className="transition-colors hover:bg-slate-50/50">
                <td className="px-6 py-4">
                  <div className="font-medium text-slate-900">{link.name}</div>
                </td>
                <td className="px-6 py-4"><StatusPill status={link.status} /></td>
                <td className="px-6 py-4 text-slate-600">{new Date(link.created_at).toLocaleDateString()}</td>
                <td className="px-6 py-4 text-slate-600">
                  {link.closed_at ? new Date(link.closed_at).toLocaleDateString() : "-"}
                </td>
                <td className="px-6 py-4">{renderActions(link, "end")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

function filterUploadLinks(links: UploadLinkResponse[], query: string) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return links;
  return links.filter((link) =>
    [
      link.name,
      link.destination ?? "",
      link.package_name ?? "",
      ...link.departure_cities,
    ]
      .join(" ")
      .toLocaleLowerCase()
      .includes(normalized),
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: Boolean(group),
    canClose: !isLoading,
    onClose,
  });
  if (!group) return null;

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-archived-group-title"
      onKeyDown={handleDialogKeyDown}
    >
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="border-b border-slate-100 px-6 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id="delete-archived-group-title" className="text-lg font-semibold text-slate-900">Delete Archived Group</h2>
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
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isLoading}
            data-dialog-initial-focus
          >
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
