"use client";

import { Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { CustomUploadQuestion } from "../api/upload-links.api";
import { GroupOptionToggle } from "./group-option-toggle";

interface CustomQuestionBuilderProps {
  questions: CustomUploadQuestion[];
  onChange: (questions: CustomUploadQuestion[]) => void;
  disabled?: boolean;
  error?: string;
}

const createQuestion = (): CustomUploadQuestion => ({
  id: crypto.randomUUID(),
  label: "",
  options: ["", ""],
  enabled: true,
  required: true,
});

export function CustomQuestionBuilder({
  questions,
  onChange,
  disabled = false,
  error,
}: CustomQuestionBuilderProps) {
  const updateQuestion = (
    index: number,
    patch: Partial<CustomUploadQuestion>,
  ) => {
    onChange(
      questions.map((question, questionIndex) => (
        questionIndex === index ? { ...question, ...patch } : question
      )),
    );
  };

  const addQuestion = () => {
    if (questions.length >= 20) return;
    onChange([...questions, createQuestion()]);
  };

  return (
    <section className="space-y-3 rounded-xl border border-dashed border-blue-200 bg-blue-50/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-900">Custom questions</h3>
          <p className="mt-1 text-sm text-slate-600">
            Ask any activity-specific question and give travellers the options they can select.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          onClick={addQuestion}
          disabled={disabled || questions.length >= 20}
          aria-label="Add custom question"
          className="shrink-0"
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>

      {questions.map((question, questionIndex) => (
        <div
          key={question.id}
          className={`rounded-xl border p-4 ${
            question.enabled
              ? "border-blue-200 bg-white"
              : "border-slate-200 bg-slate-50"
          }`}
        >
          <GroupOptionToggle
            label={question.label.trim() || `Custom question ${questionIndex + 1}`}
            description="Let travellers choose one of the options below."
            checked={question.enabled}
            onChange={(enabled) => updateQuestion(questionIndex, { enabled })}
            required={question.required ?? true}
            onRequiredChange={(required) => updateQuestion(questionIndex, { required })}
            borderless
            disabled={disabled}
          />
          <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
            <Input
              label="Question or activity name"
              value={question.label}
              disabled={disabled}
              maxLength={100}
              placeholder="e.g. T-shirt size, excursion, event session"
              onChange={(event) => updateQuestion(questionIndex, {
                label: event.target.value,
              })}
            />
            <div className="space-y-2">
              <span className="text-sm font-medium text-slate-700">Options</span>
              {question.options.map((option, optionIndex) => (
                <div key={`${question.id}-${optionIndex}`} className="flex gap-2">
                  <Input
                    value={option}
                    disabled={disabled}
                    maxLength={120}
                    aria-label={`Option ${optionIndex + 1} for ${question.label || "custom question"}`}
                    placeholder={`Option ${optionIndex + 1}`}
                    onChange={(event) => {
                      const options = [...question.options];
                      options[optionIndex] = event.target.value;
                      updateQuestion(questionIndex, { options });
                    }}
                  />
                  <button
                    type="button"
                    disabled={disabled || question.options.length <= 2}
                    aria-label={`Remove option ${optionIndex + 1}`}
                    onClick={() => updateQuestion(questionIndex, {
                      options: question.options.filter((_, index) => index !== optionIndex),
                    })}
                    className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              ))}
              <Button
                type="button"
                variant="secondary"
                disabled={disabled || question.options.length >= 50}
                onClick={() => updateQuestion(questionIndex, {
                  options: [...question.options, ""],
                })}
              >
                <Plus className="h-4 w-4" />
                Add option
              </Button>
            </div>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onChange(
                questions.filter((_, index) => index !== questionIndex),
              )}
              className="inline-flex items-center gap-2 text-sm font-medium text-red-700 hover:text-red-800 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              Remove custom question
            </button>
          </div>
        </div>
      ))}

      {questions.length === 0 && (
        <p className="rounded-lg bg-white p-3 text-sm text-slate-500">
          No custom questions yet. Use the + Add button whenever this group needs extra information.
        </p>
      )}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </section>
  );
}
