import { Input } from "@/components/ui/input";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { REVIEW_FIELDS } from "@/features/upload/components/upload-flow.constants";
import { toLabel } from "@/features/upload/services/upload-flow-helpers";

export function CompanyPassportFields({ fields, onChange }: { fields: Record<string, string>; onChange: (key: string, value: string) => void }) {
  return <div className="grid gap-4 sm:grid-cols-2">{REVIEW_FIELDS.map((key) => key.startsWith("date_of_") ? <label key={key} className="block space-y-1.5 text-sm font-medium text-slate-700">{toLabel(key)}<PassportDateInput aria-label={toLabel(key)} value={fields[key] ?? ""} onValueChange={(value) => onChange(key, value)} minIso="1900-01-01" maxIso="2200-12-31" className="min-h-11 w-full rounded-lg border-slate-300" /></label> : <Input key={key} label={toLabel(key)} maxLength={160} value={fields[key] ?? ""} onChange={(event) => onChange(key, event.target.value)} />)}</div>;
}
