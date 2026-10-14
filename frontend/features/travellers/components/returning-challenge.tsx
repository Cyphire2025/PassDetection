"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isValidPassportIsoDate } from "@/lib/utils/passport-date";
import type { ClaimTransition, DocumentQuestion } from "../types";
import { DocumentQuestionFields, QUESTION_LABELS } from "./returning-fields";

export function ReturningChallenge({ transition, pending, onVerify, onChangeQuestion }: {
  transition: ClaimTransition; pending: boolean;
  onVerify: (answers: Partial<Record<DocumentQuestion, string>>) => void;
  onChangeQuestion: (field: DocumentQuestion) => void;
}) {
  const [answers, setAnswers] = useState<Partial<Record<DocumentQuestion, string>>>({});
  const questions = transition.questions ?? [];
  return <form className="space-y-5" onSubmit={(event) => {
    event.preventDefault(); onVerify(Object.fromEntries(questions.map((field) => [field, answers[field] ?? ""])));
  }}>
    <DocumentQuestionFields questions={questions} answers={answers} onChange={(field, value) => setAnswers((current) => ({ ...current, [field]: value }))} disabled={pending} />
    {transition.can_change_question && <label className="block space-y-2 text-sm font-medium text-slate-600">
      Use another date from your passport
      <select aria-label="Change verification question" value="" disabled={pending} onChange={(event) => {
        if (event.target.value) onChangeQuestion(event.target.value as DocumentQuestion);
      }} className="min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600">
        <option value="">Choose another date</option>
        {(transition.available_questions ?? []).filter((field) => !questions.includes(field)).map((field) => <option key={field} value={field}>{QUESTION_LABELS[field]}</option>)}
      </select>
    </label>}
    <Button type="submit" isLoading={pending} disabled={!questions.length || questions.some((field) => !isValidPassportIsoDate(answers[field] ?? ""))} className="min-h-12 w-full">Verify and view passport</Button>
  </form>;
}
