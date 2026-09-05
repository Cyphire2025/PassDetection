"use client";

export function GroupOptionToggle({
  label,
  description,
  checked,
  onChange,
  borderless = false,
  disabled = false,
  required,
  onRequiredChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  borderless?: boolean;
  disabled?: boolean;
  required?: boolean;
  onRequiredChange?: (required: boolean) => void;
}) {
  const containerClassName = borderless
    ? "flex items-start justify-between gap-4"
    : `flex items-start justify-between gap-4 rounded-xl border p-4 transition-colors ${
      checked ? "border-blue-200 bg-blue-50/40" : "border-slate-200 bg-white"
    }`;

  return (
    <div className={containerClassName}>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-800">{label}</p>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={`${checked ? "Disable" : "Enable"} ${label}`}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-7 w-12 shrink-0 overflow-hidden rounded-full border transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60 ${
          checked ? "border-blue-600 bg-blue-600" : "border-slate-300 bg-slate-200"
        }`}
      >
        <span
          className={`pointer-events-none absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow-sm ring-1 ring-slate-900/5 transition-transform duration-200 ${
            checked ? "translate-x-5" : "translate-x-0"
          }`}
        />
      </button>
      {onRequiredChange && (
        <label className={`inline-flex cursor-pointer items-center gap-1.5 text-xs ${checked ? "text-slate-600" : "text-slate-400"}`}>
          <input
            type="checkbox"
            checked={required ?? true}
            onChange={(event) => onRequiredChange(event.target.checked)}
            disabled={disabled || !checked}
            aria-label={`Make ${label} compulsory`}
            className="h-3.5 w-3.5 rounded border-slate-300 accent-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed"
          />
          Compulsory
        </label>
      )}
      </div>
    </div>
  );
}
