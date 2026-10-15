import Link from "next/link";
import { ROUTES } from "@/constants/routes";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";
import { formatPassportCountry } from "@/lib/utils/passport-country";
import type { CompanyOriginalRecord as OriginalRecord } from "../types/company-people";

export function CompanyOriginalRecord({ record }: { record: OriginalRecord }) {
  return <section className="space-y-3 rounded-xl border border-slate-200 p-4" aria-label="Original trip record">
    <div><h3 className="text-sm font-semibold text-slate-950">Original trip record</h3><p className="mt-1 text-xs text-slate-500">Historical details. Add a reviewed document to create a current passport version.</p></div>
    <p className="text-xs text-slate-500">{record.status.replaceAll("_", " ")} · Revision {record.source_revision} · {new Date(record.created_at).toLocaleDateString()}</p>
    <dl className="grid gap-4 sm:grid-cols-2">{Object.entries(record.fields).filter(([, value]) => value).map(([field, value]) => <div key={field} className="min-w-0"><dt className="text-xs font-medium text-slate-500">{toLabel(field)}</dt><dd className="mt-1 break-words text-sm text-slate-950">{field === "issuing_country" || field === "nationality" ? formatPassportCountry(value) : value}</dd></div>)}</dl>
    <Link prefetch={false} href={ROUTES.dashboard.passportDetail(record.source_id)} className="inline-flex min-h-11 items-center text-sm font-medium text-blue-800 hover:underline">View original record</Link>
  </section>;
}
