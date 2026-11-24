import { BadgeCheck } from "lucide-react";
import type { CustomUploadDetail, CustomUploadQuestion } from "@/features/passports/api/upload-links.api";
import { ContactInput } from "./upload-contact-input";

export function CustomQuestionFields({
  questions,
  answers,
  onChange,
}: {
  questions: CustomUploadQuestion[];
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-blue-100 bg-blue-50/40 p-4 sm:grid-cols-2">
      {questions.map((question) => (
        <label key={question.id} className="block min-w-0 space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {question.label}{question.required !== false ? " *" : " (optional)"}
          </span>
          <select
            value={answers[question.id] ?? ""}
            onChange={(event) => onChange(question.id, event.target.value)}
            className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            required={question.required !== false}
          >
            <option value="">Select an option</option>
            {question.options.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}

export function CustomDetailFields({
  details,
  answers,
  onChange,
}: {
  details: CustomUploadDetail[];
  answers: Record<string, string>;
  onChange: (detailId: string, value: string) => void;
}) {
  if (details.length === 0) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-violet-100 bg-violet-50/40 p-4 sm:grid-cols-2">
      {details.map((detail) => (
        <ContactInput
          key={detail.id}
          icon={<BadgeCheck className="h-5 w-5" />}
          label={detail.label}
          type="text"
          value={answers[detail.id] ?? ""}
          onChange={(value) => onChange(detail.id, value)}
          required={detail.required !== false}
          maxLength={500}
        />
      ))}
    </div>
  );
}
