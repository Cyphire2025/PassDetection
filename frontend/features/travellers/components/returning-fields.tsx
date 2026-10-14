"use client";

import { Input } from "@/components/ui/input";
import { PassportDateInput } from "@/components/shared/passport-date-input";
import type { DocumentQuestion } from "../types";

export const QUESTION_LABELS: Record<DocumentQuestion, string> = { date_of_birth: "Date of birth", issue_date: "Passport issue date", expiry_date: "Passport expiry date" };

export function PassportProofFields({ number, onNumber, disabled }: {
  number: string; onNumber: (value: string) => void; disabled?: boolean;
}) {
  return <div className="space-y-4">
    <Input label="Full passport number" value={number} onChange={(event) => onNumber(event.target.value)} required minLength={3} maxLength={32} autoComplete="off" spellCheck={false} disabled={disabled} hint="Enter the complete number from your passport, including leading zeros." className="h-12 text-base" />
  </div>;
}

export function DocumentQuestionFields({ questions, answers, onChange, disabled }: { questions: DocumentQuestion[]; answers: Partial<Record<DocumentQuestion, string>>; onChange: (field: DocumentQuestion, answer: string) => void; disabled?: boolean }) {
  return <div className="space-y-4">{questions.map((question) => <PassportDateInput key={question} label={QUESTION_LABELS[question]} value={answers[question] ?? ""} onValueChange={(value) => onChange(question, value)} minIso="1900-01-01" maxIso="2200-12-31" required disabled={disabled} autoComplete="off" hint="Use the date printed on the passport used for this check (DD/MM/YYYY)." className="h-12 text-base" />)}</div>;
}
