"use client";

import { Button } from "@/components/ui/button";
import { useCompanyDocumentUpload, type CompanyDocumentUploadProps } from "../hooks/use-company-document-upload";
import { CompanyError } from "./company-feedback";
import { DocumentUploadSelection } from "./document-upload/selection";
import { DocumentUploadReview } from "./document-upload/review";

export function CompanyDocumentUploadForm(props: CompanyDocumentUploadProps) {
  const controller = useCompanyDocumentUpload(props);
  return <form className="space-y-4 rounded-xl border border-blue-100 bg-blue-50/30 p-3 sm:p-4" onSubmit={controller.submit}>
    <div>
      <h3 className="text-sm font-semibold text-slate-950">Add document version</h3>
      <p className="mt-1 text-xs leading-5 text-slate-500">The new image becomes current. Previous versions and trip records are kept.</p>
    </div>
    <fieldset disabled={controller.pending} className="space-y-4">
      <DocumentUploadSelection controller={controller} />
      <DocumentUploadReview controller={controller} />
    </fieldset>
    {controller.error && <CompanyError message={controller.error} />}
    <div className="flex flex-wrap justify-end gap-2">
      <Button type="button" variant="secondary" disabled={controller.pending} onClick={props.onCancel}>Cancel</Button>
      <Button type="submit" disabled={!controller.canSave} isLoading={controller.pending}>Save document version</Button>
    </div>
  </form>;
}
