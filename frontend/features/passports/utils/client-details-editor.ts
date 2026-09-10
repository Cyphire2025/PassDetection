import type { ClientDetailsEditorResponse, ClientDetailsPatch, ClientDetailKey } from "../api/client-details.api";

export interface ClientDetailsDraft {
  fields: Partial<Record<ClientDetailKey, string>>;
  questions: Record<string, string>;
  details: Record<string, string>;
}

export function createClientDetailsDraft(data: ClientDetailsEditorResponse): ClientDetailsDraft {
  return {
    fields: Object.fromEntries(data.fields.map((field) => [field.key, field.value ?? ""])),
    questions: Object.fromEntries(data.custom_answers.map((answer) => [answer.question_id, answer.value ?? ""])),
    details: Object.fromEntries(data.custom_detail_answers.map((answer) => [answer.detail_id, answer.value ?? ""])),
  };
}

/** Send changed values only; labels, unrelated fields and historical snapshots remain server-owned. */
export function buildClientDetailsPatch(data: ClientDetailsEditorResponse, draft: ClientDetailsDraft): ClientDetailsPatch {
  const patch: ClientDetailsPatch = { expected_updated_at: data.updated_at };
  for (const field of data.fields) {
    const value = draft.fields[field.key] ?? "";
    if (value !== (field.value ?? "")) patch[field.key] = value.trim() || null;
  }
  const questions = data.custom_answers.flatMap((answer) => {
    const value = draft.questions[answer.question_id] ?? "";
    return value !== (answer.value ?? "") ? [{ question_id: answer.question_id, value: value.trim() }] : [];
  });
  const details = data.custom_detail_answers.flatMap((answer) => {
    const value = draft.details[answer.detail_id] ?? "";
    return value !== (answer.value ?? "") ? [{ detail_id: answer.detail_id, value: value.trim() }] : [];
  });
  if (questions.length) patch.custom_answers = questions;
  if (details.length) patch.custom_detail_answers = details;
  return patch;
}

export function clientDetailsValidation(data: ClientDetailsEditorResponse, draft: ClientDetailsDraft): string | null {
  const fields: Array<{ label: string; value: string | null; required: boolean; max_length: number; type: string; options: string[]; next: string }> = [
    ...data.fields.map((field) => ({ ...field, next: draft.fields[field.key] ?? "" })),
    ...data.custom_answers.map((field) => ({ ...field, type: field.options.length ? "select" : "text", next: draft.questions[field.question_id] ?? "" })),
    ...data.custom_detail_answers.map((field) => ({ ...field, type: "text", options: [], next: draft.details[field.detail_id] ?? "" })),
  ];
  for (const field of fields) {
    if (field.next === (field.value ?? "")) continue;
    const value = field.next.trim();
    if (field.required && !value) return `${field.label} is required.`;
    if (value.length > field.max_length) return `${field.label} must be ${field.max_length} characters or fewer.`;
    if (value && field.type === "email" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return `Enter a valid ${field.label.toLowerCase()}.`;
    if (value && field.type === "select" && !field.options.includes(value)) return `Choose an available option for ${field.label}.`;
  }
  return null;
}

export function clientDetailsError(error: unknown): { message: string; conflict: boolean } {
  const value = error as { status?: number; code?: string; message?: string } | null;
  const conflict = value?.status === 409 || value?.code === "HTTP_409";
  return {
    conflict,
    message: conflict
      ? "This record changed or is temporarily locked by another operation. Your edits have not been applied. Reload the latest details before trying again."
      : value?.message || "The details could not be saved. Your edits are still here; check the connection and try again.",
  };
}
