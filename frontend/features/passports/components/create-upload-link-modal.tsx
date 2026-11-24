"use client";

import { X } from "lucide-react";
import { CompanyWorkspaceFeedback } from "@/features/companies/components/company-agency-scope";
import { useCompanyWorkspace, type CompanyWorkspace } from "@/features/companies/hooks/use-company-workspace";
import { useCreateUploadLinkForm } from "./use-create-upload-link-form";
import { CreateUploadLinkDetails } from "./create-upload-link-details";
import { CreateUploadLinkResult } from "./create-upload-link-result";

export interface CreateUploadLinkModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateUploadLinkModal(props: CreateUploadLinkModalProps) {
  const workspace = useCompanyWorkspace(props.isOpen);
  // Retain the draft on a failed revalidation; agencyId still gates every control.
  const resolvedAgencyId = workspace.data?.agency_id ?? null;
  return <CreateUploadLinkForm key={`${workspace.sessionKey}:${resolvedAgencyId}`} {...props} workspace={workspace} />;
}

function CreateUploadLinkForm({ isOpen, onClose, workspace }: CreateUploadLinkModalProps & { workspace: CompanyWorkspace }) {
  const state = useCreateUploadLinkForm({ isOpen, onClose, workspace });
  const {
    dialogRef,
    handleKeyDown,
    titleId,
    isPending,
    createdImportGroupId,
    hasGeneratedTargets,
    handleClose,
    agencyId,
    isCreated
  } = state;
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div
        ref={dialogRef}
        onKeyDown={handleKeyDown}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isPending}
        className="max-h-[90vh] w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200"
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 id={titleId} className="text-lg font-semibold text-slate-800">
            {createdImportGroupId ? "Group Created" : hasGeneratedTargets ? "Links Generated" : "Create Upload Link"}
          </h2>
          <button
            type="button"
            onClick={handleClose}
            disabled={isPending}
            aria-label="Close create upload link dialog"
            className="rounded-full p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[calc(90vh-73px)] overflow-y-auto p-6">
          {!agencyId ? <CompanyWorkspaceFeedback workspace={workspace} /> : isCreated ? (
            <CreateUploadLinkResult state={state} />
          ) : (
            <CreateUploadLinkDetails state={state} />
          )}
        </div>
      </div>
    </div>
  );
}
