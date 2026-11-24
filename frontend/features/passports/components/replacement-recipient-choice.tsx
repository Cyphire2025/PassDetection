import { CheckCircle2 } from "lucide-react";
import { fieldLabel } from "./group-whatsapp-tracking-model";
import type { ReplacementCandidate } from "../api/upload-links.api";

interface Props {
  candidate: ReplacementCandidate;
  isSelected: boolean;
  disabled: boolean;
  groupName: string;
  onSelect: (recipientId: string) => void;
}

export function ReplacementRecipientChoice({
  candidate,
  isSelected,
  disabled,
  groupName,
  onSelect,
}: Props) {
  const details = Object.entries(candidate.imported_fields).filter(([, value]) => value.trim());
  return (
    <div
      className={`overflow-hidden rounded-xl border transition ${
        isSelected
          ? "border-blue-500 bg-blue-50 ring-2 ring-blue-100"
          : "border-slate-200 bg-white hover:border-slate-300"
      }`}
    >
      <label
        className={`flex w-full items-start gap-3 p-4 text-left focus-within:ring-2 focus-within:ring-inset focus-within:ring-blue-500 ${disabled ? "cursor-default opacity-60" : "cursor-pointer"}`}
      >
        <input
          type="radio"
          name={groupName}
          value={candidate.recipient_id}
          checked={isSelected}
          disabled={disabled}
          onChange={() => {
            onSelect(candidate.recipient_id);
          }}
          className="sr-only"
        />
        <span
          aria-hidden="true"
          className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
            isSelected
              ? "border-blue-600 bg-blue-600 text-white"
              : "border-slate-300 bg-white"
          }`}
        >
          {isSelected && (
            <CheckCircle2
              className="h-3.5 w-3.5"
              aria-hidden="true"
            />
          )}
        </span>
        <span className="min-w-0 flex-1">
              <span className="block break-words font-semibold text-slate-900">
            {candidate.name?.trim() || "Unnamed recipient"}
          </span>
          <span className="mt-0.5 block text-sm text-slate-600">
            {candidate.phone}
          </span>
          <span className="mt-2 flex flex-wrap gap-1.5">
            {candidate.broadcast_names.map((name) => (
              <span
                key={name}
                className="rounded-full bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800"
              >
                {name}
              </span>
            ))}
          </span>
        </span>
      </label>
      {details.length > 0 && (
        <details className="border-t border-slate-100 px-4 py-3">
          <summary className="cursor-pointer text-xs font-semibold text-blue-700">
            View imported details
          </summary>
          <dl className="mt-3 grid gap-2 sm:grid-cols-2">
            {details.map(([key, value]) => (
              <div key={key} className="min-w-0">
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                  {fieldLabel(key)}
                </dt>
                <dd className="break-words text-xs text-slate-700">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
