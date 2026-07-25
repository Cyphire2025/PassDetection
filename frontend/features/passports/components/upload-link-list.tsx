"use client";

import { Archive, Check, CheckCircle2, Clock, Copy, Link2, Pencil, RotateCcw, Trash2, X, XCircle } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/ui";
import { copyTextToClipboard } from "@/lib/utils/clipboard";
import { getPassportUploadTargets } from "@/lib/utils/public-url";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import type {
  CustomUploadDetail,
  CustomUploadQuestion,
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
import { CreateUploadLinkModal } from "./create-upload-link-modal";
import { GroupOptionToggle } from "./group-option-toggle";
import { CustomQuestionBuilder } from "./custom-question-builder";
import { CustomDetailBuilder } from "./custom-detail-builder";

export function UploadLinkList() {
  const role = useAuthStore(selectUserRole);
  const canPermanentlyDelete = role !== "agency_staff";
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
  const [editAllowFilesFromDevice, setEditAllowFilesFromDevice] = useState(true);
  const [editAskNearestDomesticAirport, setEditAskNearestDomesticAirport] = useState(false);
  const [editRelationWithQualifier, setEditRelationWithQualifier] = useState(false);
  const [editDesignation, setEditDesignation] = useState(false);
  const [editAgencyDealershipName, setEditAgencyDealershipName] = useState(false);
  const [editCustomQuestions, setEditCustomQuestions] = useState<CustomUploadQuestion[]>([]);
  const [editCustomDetails, setEditCustomDetails] = useState<CustomUploadDetail[]>([]);
  const { data: activeLinks = [], isLoading: isLoadingActive } = useUploadLinks();
  const { data: archivedLinks = [], isLoading: isLoadingArchived } = useUploadLinks("archived");
  const { mutate: closeLink, isPending: isClosing } = useRevokeUploadLink();
  const { mutate: archiveLink, isPending: isArchiving } = useDeleteUploadLink();
  const { mutate: restoreLink, isPending: isRestoring } = useRestoreUploadLink();
  const { mutate: renameLink, isPending: isRenaming } = useUpdateUploadLink();
  const { mutate: permanentlyDeleteLink, isPending: isPermanentlyDeleting } = usePermanentlyDeleteUploadLink();

  const openGroupEditor = (link: UploadLinkResponse) => {
    setRenameTarget(link);
    setRenameValue(link.name);
    setEditAllowFilesFromDevice(link.allow_files_from_device ?? true);
    setEditAskNearestDomesticAirport(link.ask_nearest_domestic_airport ?? false);
    setEditRelationWithQualifier(link.relation_with_qualifier_enabled ?? false);
    setEditDesignation(link.designation_enabled ?? false);
    setEditAgencyDealershipName(link.agency_dealership_name_enabled ?? false);
    setEditCustomQuestions(link.custom_questions ?? []);
    setEditCustomDetails(link.custom_details ?? []);
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
          onRename={openGroupEditor}
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
        allowFilesFromDevice={editAllowFilesFromDevice}
        askNearestDomesticAirport={editAskNearestDomesticAirport}
        relationWithQualifier={editRelationWithQualifier}
        designation={editDesignation}
        agencyDealershipName={editAgencyDealershipName}
        customQuestions={editCustomQuestions}
        customDetails={editCustomDetails}
        isLoading={isRenaming}
        onNameChange={setRenameValue}
        onAllowFilesFromDeviceChange={setEditAllowFilesFromDevice}
        onAskNearestDomesticAirportChange={setEditAskNearestDomesticAirport}
        onRelationWithQualifierChange={setEditRelationWithQualifier}
        onDesignationChange={setEditDesignation}
        onAgencyDealershipNameChange={setEditAgencyDealershipName}
        onCustomQuestionsChange={setEditCustomQuestions}
        onCustomDetailsChange={setEditCustomDetails}
        onClose={() => setRenameTarget(null)}
        onConfirm={() => {
          if (!renameTarget) return;
          const nextName = renameValue.trim();
          const hasChanges = nextName !== renameTarget.name
            || editAllowFilesFromDevice !== (renameTarget.allow_files_from_device ?? true)
            || editAskNearestDomesticAirport !== (renameTarget.ask_nearest_domestic_airport ?? false)
            || editRelationWithQualifier
              !== (renameTarget.relation_with_qualifier_enabled ?? false)
            || editDesignation !== (renameTarget.designation_enabled ?? false)
            || editAgencyDealershipName
              !== (renameTarget.agency_dealership_name_enabled ?? false)
            || JSON.stringify(editCustomQuestions)
              !== JSON.stringify(renameTarget.custom_questions ?? [])
            || JSON.stringify(editCustomDetails)
              !== JSON.stringify(renameTarget.custom_details ?? []);
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
              departure_cities: renameTarget.departure_cities,
              base_city_enabled: renameTarget.base_city_enabled,
              nearest_international_airport_enabled: renameTarget.nearest_international_airport_enabled,
              staff_code_enabled: renameTarget.staff_code_enabled,
              agent_employee_code_enabled: renameTarget.agent_employee_code_enabled,
              meal_preference_enabled: renameTarget.meal_preference_enabled,
              require_selfie: renameTarget.require_selfie,
              allow_files_from_device: editAllowFilesFromDevice,
              ask_nearest_domestic_airport: editAskNearestDomesticAirport,
              relation_with_qualifier_enabled: editRelationWithQualifier,
              designation_enabled: editDesignation,
              agency_dealership_name_enabled: editAgencyDealershipName,
              custom_questions: editCustomQuestions,
              custom_details: editCustomDetails,
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
  allowFilesFromDevice,
  askNearestDomesticAirport,
  relationWithQualifier,
  designation,
  agencyDealershipName,
  customQuestions,
  customDetails,
  isLoading,
  onNameChange,
  onAllowFilesFromDeviceChange,
  onAskNearestDomesticAirportChange,
  onRelationWithQualifierChange,
  onDesignationChange,
  onAgencyDealershipNameChange,
  onCustomQuestionsChange,
  onCustomDetailsChange,
  onConfirm,
  onClose,
}: {
  group: UploadLinkResponse | null;
  name: string;
  allowFilesFromDevice: boolean;
  askNearestDomesticAirport: boolean;
  relationWithQualifier: boolean;
  designation: boolean;
  agencyDealershipName: boolean;
  customQuestions: CustomUploadQuestion[];
  customDetails: CustomUploadDetail[];
  isLoading: boolean;
  onNameChange: (value: string) => void;
  onAllowFilesFromDeviceChange: (checked: boolean) => void;
  onAskNearestDomesticAirportChange: (checked: boolean) => void;
  onRelationWithQualifierChange: (checked: boolean) => void;
  onDesignationChange: (checked: boolean) => void;
  onAgencyDealershipNameChange: (checked: boolean) => void;
  onCustomQuestionsChange: (questions: CustomUploadQuestion[]) => void;
  onCustomDetailsChange: (details: CustomUploadDetail[]) => void;
  onConfirm: () => void;
  onClose: () => void;
}) {
  if (!group) return null;
  const customQuestionsValid = customQuestions.every((question) => {
    const options = question.options.map((option) => option.trim()).filter(Boolean);
    return Boolean(question.label.trim())
      && options.length >= 2
      && new Set(options.map((option) => option.toLocaleLowerCase())).size
        === options.length;
  });
  const normalizedDetailNames = customDetails.map(
    (detail) => detail.label.trim().toLocaleLowerCase(),
  );
  const customDetailsValid = (
    normalizedDetailNames.every(Boolean)
    && new Set(normalizedDetailNames).size === normalizedDetailNames.length
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-passport-group-title"
    >
      <form
        className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
        onSubmit={(event) => {
          event.preventDefault();
          onConfirm();
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
            autoFocus
            disabled={isLoading}
            onChange={(event) => onNameChange(event.target.value)}
          />
          <GroupOptionToggle
            label="Allow files from device"
            description="When disabled, travellers must capture both passport pages with the live camera."
            checked={allowFilesFromDevice}
            disabled={isLoading}
            onChange={onAllowFilesFromDeviceChange}
          />
          <GroupOptionToggle
            label="Ask for nearest domestic airport"
            description="When enabled, each traveller must provide their nearest domestic airport during review."
            checked={askNearestDomesticAirport}
            disabled={isLoading}
            onChange={onAskNearestDomesticAirportChange}
          />
          <GroupOptionToggle
            label="Relation with Qualifier"
            description="Require Self or one approved family relationship before this single-passenger upload."
            checked={relationWithQualifier}
            disabled={isLoading}
            onChange={onRelationWithQualifierChange}
          />
          <GroupOptionToggle
            label="Designation"
            description="Require each traveller to type their designation."
            checked={designation}
            disabled={isLoading}
            onChange={onDesignationChange}
          />
          <GroupOptionToggle
            label="Agency/Dealership Name"
            description="Require each traveller to type their agency or dealership name."
            checked={agencyDealershipName}
            disabled={isLoading}
            onChange={onAgencyDealershipNameChange}
          />
          <CustomQuestionBuilder
            questions={customQuestions}
            onChange={onCustomQuestionsChange}
            disabled={isLoading}
          />
          <CustomDetailBuilder
            details={customDetails}
            onChange={onCustomDetailsChange}
            disabled={isLoading}
            error={
              customDetailsValid
                ? undefined
                : "Custom detail headings are required and must be unique."
            }
          />
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button
            type="submit"
            isLoading={isLoading}
            disabled={!name.trim() || !customQuestionsValid || !customDetailsValid}
          >
            Save changes
          </Button>
        </div>
      </form>
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
  canPermanentlyDelete?: boolean;
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
  canPermanentlyDelete = true,
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
