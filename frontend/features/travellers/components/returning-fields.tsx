"use client";

import { Input } from "@/components/ui/input";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import { getPassportCountryOptions } from "@/lib/utils/passport-country";
import type { DocumentQuestion } from "../types";

const COUNTRIES = getPassportCountryOptions(3);
export const QUESTION_LABELS: Record<DocumentQuestion, string> = { date_of_birth: "Date of birth", issue_date: "Passport issue date", expiry_date: "Passport expiry date" };

export function PassportProofFields({ number, issuer, onNumber, onIssuer, disabled }: {
  number: string; issuer: string; onNumber: (value: string) => void; onIssuer: (value: string) => void; disabled?: boolean;
}) {
  return <div className="space-y-4">
    <Input label="Full passport number" value={number} onChange={(event) => onNumber(event.target.value)} required minLength={3} maxLength={32} autoComplete="off" spellCheck={false} disabled={disabled} hint="Enter the complete number from your passport, including leading zeros." className="h-12 text-base" />
    <label className="block space-y-2 text-sm font-medium text-slate-700">Issuing country<select required value={issuer} onChange={(event) => onIssuer(event.target.value)} disabled={disabled} className="h-12 w-full min-w-0 rounded-xl border border-slate-300 bg-white px-3 text-base focus:outline-none focus:ring-2 focus:ring-blue-600"><option value="">Select issuing country</option>{COUNTRIES.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}</select><span className="block text-xs font-normal text-slate-500">The country that issued the passport; this may differ from your nationality.</span></label>
  </div>;
}

export function DocumentQuestionFields({ questions, answers, onChange, disabled }: { questions: DocumentQuestion[]; answers: Partial<Record<DocumentQuestion, string>>; onChange: (field: DocumentQuestion, answer: string) => void; disabled?: boolean }) {
  return <div className="space-y-4">{questions.map((question) => <PassportDateInput key={question} label={QUESTION_LABELS[question]} value={answers[question] ?? ""} onValueChange={(value) => onChange(question, value)} minIso="1900-01-01" maxIso="2200-12-31" required disabled={disabled} autoComplete="off" hint="Use the date printed on the passport used for this check (DD/MM/YYYY)." className="h-12 text-base" />)}</div>;
}
