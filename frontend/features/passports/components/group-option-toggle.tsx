"use client";

export function GroupOptionToggle({
  label,
  description,
  checked,
  onChange,
  borderless = false,
  disabled = false,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  borderless?: boolean;
  disabled?: boolean;
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
    </div>
  );
}
