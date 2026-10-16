"use client";

import { Check, ClipboardCheck, FileCheck2 } from "lucide-react";
import { useId } from "react";
import { DOCUMENT_DISTRIBUTION_LANES } from "@/features/documents/config/document-distribution-lanes";
import type { GroupUpdateAudience, GroupUpdateRecipient } from "../api/group-updates.api";
import { updateAudienceMatches } from "../utils/group-update-audience";

function AudienceChoices({ title, description, value, choices, disabled, onChange }: {
  title: string; description: string; value: string; choices: { value: string; label: string; count: number }[]; disabled: boolean; onChange: (value: string) => void;
}) {
  const name = useId();
  return <fieldset disabled={disabled} className="min-w-0 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
    <legend className="sr-only">{title}</legend>
    <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">{title === "Document submission" ? <ClipboardCheck className="h-4 w-4 text-blue-600" /> : <FileCheck2 className="h-4 w-4 text-blue-600" />}{title}</div>
    <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
    <div className="mt-4 grid grid-cols-3 gap-2">{choices.map(choice => <label key={choice.value} className={`relative flex min-w-0 cursor-pointer flex-col gap-2 rounded-lg border px-3 py-3 transition focus-within:ring-2 focus-within:ring-blue-500 ${disabled ? "cursor-not-allowed opacity-60" : "hover:border-blue-300"} ${value === choice.value ? "border-blue-600 bg-blue-50 text-blue-900 ring-1 ring-blue-600" : "border-slate-200 text-slate-600"}`}>
      <input className="sr-only" type="radio" name={name} aria-label={`${title}: ${choice.label}`} value={choice.value} checked={value === choice.value} onChange={() => onChange(choice.value)} />
      <span className="flex items-center justify-between gap-1 text-xs font-semibold sm:text-sm">{choice.label}{value === choice.value ? <Check aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-blue-700" /> : null}</span>
      <span className="text-lg font-semibold tabular-nums sm:text-xl">{choice.count.toLocaleString()}</span>
    </label>)}</div>
  </fieldset>;
}

export function GroupUpdateAudienceFields({ audience, rows, loading, disabled, onChange, mode = "send" }: {
  audience: GroupUpdateAudience; rows: GroupUpdateRecipient[]; loading: boolean; disabled: boolean; onChange: (value: GroupUpdateAudience) => void; mode?: "send" | "review";
}) {
  const id = useId();
  const count = (change: Partial<GroupUpdateAudience>) => rows.filter(row => updateAudienceMatches(row, { ...audience, ...change })).length;
  const heading = mode === "review" ? "Filter recipients" : "Choose your audience";
  return <section aria-label={heading} className="space-y-3">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-semibold text-slate-900">{heading}</h3><p className="text-xs text-slate-500">Both boxes apply together.{mode === "review" ? " Delivery statuses below apply to these matching travellers." : " Counts show matching travellers."}</p></div>
    <div className="grid items-start gap-4 md:grid-cols-2">
      <div className="space-y-3"><AudienceChoices title="Document submission" description="Has the traveller completed their document submission?" value={audience.submission_status} disabled={disabled || loading} onChange={value => onChange({ ...audience, submission_status: value as GroupUpdateAudience["submission_status"] })} choices={[{ value: "all", label: "All", count: count({ submission_status: "all" }) }, { value: "submitted", label: "Submitted", count: count({ submission_status: "submitted" }) }, { value: "not_submitted", label: "Not submitted", count: count({ submission_status: "not_submitted" }) }]} />
        <div className="rounded-xl border border-slate-200 bg-white p-4 text-xs leading-5 text-slate-500"><p className="font-semibold text-slate-700">Which WhatsApp number is used?</p><p className="mt-2"><strong>Submitted:</strong> the number in their completed submission.</p><p className="mt-1"><strong>Not submitted:</strong> their imported broadcast number.</p></div>
      </div>
      <div className="space-y-3"><AudienceChoices title="Document distribution" description="Have we successfully sent the traveller’s visa or ticket?" value={audience.document_status} disabled={disabled || loading} onChange={value => onChange({ ...audience, document_status: value as GroupUpdateAudience["document_status"] })} choices={[{ value: "all", label: "All", count: count({ document_status: "all" }) }, { value: "sent", label: "Sent", count: count({ document_status: "sent" }) }, { value: "pending", label: "Pending", count: count({ document_status: "pending" }) }]} />
        <div className="rounded-xl border border-slate-200 bg-white p-4"><label htmlFor={id} className="block text-xs font-semibold text-slate-700">Document type</label><select id={id} value={audience.document_type} disabled={disabled} onChange={event => onChange({ ...audience, document_type: event.target.value as GroupUpdateAudience["document_type"] })} className="mt-2 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm disabled:opacity-50">{Object.values(DOCUMENT_DISTRIBUTION_LANES).map(lane => <option key={lane.documentType} value={lane.documentType}>{lane.workflowLabel}</option>)}</select><p className="mt-2 text-xs leading-5 text-slate-500">Pending includes missing documents and failed, unknown or partly completed sends.</p></div>
      </div>
    </div>
  </section>;
}
