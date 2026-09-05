"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { CustomUploadDetail } from "../api/upload-links.api";
import { GroupOptionToggle } from "./group-option-toggle";

interface CustomDetailBuilderProps {
  details: CustomUploadDetail[];
  onChange: (details: CustomUploadDetail[]) => void;
  disabled?: boolean;
  error?: string;
}

const createDetail = (): CustomUploadDetail => ({
  id: crypto.randomUUID(),
  label: "",
  enabled: true,
  required: true,
});

export function CustomDetailBuilder({
  details,
  onChange,
  disabled = false,
  error,
}: CustomDetailBuilderProps) {
  const updateDetail = (
    index: number,
    patch: Partial<CustomUploadDetail>,
  ) => {
    onChange(details.map((detail, detailIndex) => (
      detailIndex === index ? { ...detail, ...patch } : detail
    )));
  };

  return (
    <section className="space-y-3 rounded-xl border border-dashed border-violet-200 bg-violet-50/30 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-900">Custom Detail</h3>
          <p className="mt-1 text-sm text-slate-600">
            Add headings for information travellers can type in their own words.
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={disabled || details.length >= 20}
          onClick={() => onChange([...details, createDetail()])}
          aria-label="Add custom detail"
          className="shrink-0"
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>

      {details.map((detail, index) => (
        <div
          key={detail.id}
          className={`rounded-xl border p-4 ${
            detail.enabled
              ? "border-violet-200 bg-white"
              : "border-slate-200 bg-slate-50"
          }`}
        >
          <GroupOptionToggle
            label={detail.label.trim() || `Custom detail ${index + 1}`}
            description="Let travellers provide a typed answer for this detail."
            checked={detail.enabled}
            onChange={(enabled) => updateDetail(index, { enabled })}
            required={detail.required ?? true}
            onRequiredChange={(required) => updateDetail(index, { required })}
            borderless
            disabled={disabled}
          />
          <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
            <Input
              label="Custom heading"
              value={detail.label}
              maxLength={100}
              disabled={disabled}
              placeholder="e.g. Membership number, preferred activity"
              onChange={(event) => updateDetail(index, {
                label: event.target.value,
              })}
            />
            <button
              type="button"
              disabled={disabled}
              onClick={() => onChange(
                details.filter((_, detailIndex) => detailIndex !== index),
              )}
              className="inline-flex items-center gap-2 text-sm font-medium text-red-700 hover:text-red-800 disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
              Remove custom detail
            </button>
          </div>
        </div>
      ))}

      {details.length === 0 && (
        <p className="rounded-lg bg-white p-3 text-sm text-slate-500">
          No custom details yet. Use + Add to request a typed value.
        </p>
      )}
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    </section>
  );
}
