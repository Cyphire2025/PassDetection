import { Input } from "@/components/ui/input";
import type { CurrentDetailField } from "../types";

/** Server descriptors use the same collection rules as a fresh submission. */
export function ReturningCurrentDetails({ fields, values, onChange }: { fields: CurrentDetailField[]; values: Record<string, string>; onChange: (key: string, value: string) => void }) {
  if (!fields.length) return null;
  return <div className="mt-5 grid gap-4 sm:grid-cols-2">{fields.map((field) => field.type === "select" ? <label key={field.key} className="block min-w-0 space-y-1.5 text-sm font-medium text-slate-700">{field.label}{field.required ? " *" : " (optional)"}<select value={values[field.key] ?? ""} onChange={(event) => onChange(field.key, event.target.value)} required={field.required} className="min-h-12 w-full rounded-xl border border-slate-300 bg-white px-3 text-base"><option value="">Select an option</option>{field.options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label> : <Input key={field.key} label={`${field.label}${field.required ? "" : " (optional)"}`} type={field.type} value={values[field.key] ?? ""} required={field.required} maxLength={500} onChange={(event) => onChange(field.key, event.target.value)} className="h-12 text-base" />)}</div>;
}
