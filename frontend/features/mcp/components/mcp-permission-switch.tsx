"use client";

export function McpPermissionSwitch({ label, description, checked, disabled, onChange }: {
  label: string; description?: string; checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void;
}) {
  return <label className="relative flex items-start justify-between gap-5">
    <span className="min-w-0"><span className="block text-sm font-medium text-slate-950">{label}</span>
      {description ? <span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span> : null}</span>
    <input type="checkbox" role="switch" aria-label={label} checked={checked} disabled={disabled} onChange={(event) => onChange(event.target.checked)} className="peer absolute right-0 top-0.5 z-10 h-6 w-11 cursor-pointer opacity-0 disabled:cursor-not-allowed" />
    <span aria-hidden="true" className="pointer-events-none relative mt-0.5 h-6 w-11 shrink-0 rounded-full bg-slate-200 transition-colors after:absolute after:left-1 after:top-1 after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:bg-blue-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-600 peer-focus-visible:ring-offset-2 peer-disabled:opacity-50" />
  </label>;
}
