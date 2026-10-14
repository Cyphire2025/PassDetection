import { REVIEW_FIELDS } from "@/features/upload/components/upload-flow.constants";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";
import { formatPassportCountry } from "@/lib/utils/passport-country";
import type { CompanyPersonRecord } from "../types/company-people";
import { CompanyOriginalRecord } from "./company-original-record";

export function CompanyPersonDetails({ record }: { record: CompanyPersonRecord }) {
  return <div className="space-y-5"><section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-6">
    <h2 className="mb-5 text-base font-semibold text-slate-950">Current details</h2>
    <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2 xl:grid-cols-3">
      <Detail label="Full name" value={record.display_name} /><Detail label="Contact number" value={record.phone_number} />
      {record.current_document && <><Detail label="Issuing country" value={formatPassportCountry(record.current_document.issuing_country)} />
        {REVIEW_FIELDS.map((field) => <Detail key={field} label={toLabel(field)} value={field === "nationality" ? formatPassportCountry(record.current_document?.fields[field]) : record.current_document?.fields[field]} />)}</>}
    </dl>
    {!record.current_document && <p className="mt-4 text-sm text-slate-500">No accepted passport is available yet.</p>}
  </section>{!record.current_document && record.original_record && <CompanyOriginalRecord record={record.original_record} />}</div>;
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return <div className="min-w-0"><dt className="text-xs font-medium text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-medium text-slate-900">{value || "—"}</dd></div>;
}
