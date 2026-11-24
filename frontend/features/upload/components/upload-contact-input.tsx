import { useId, type ReactNode } from "react";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { Input } from "@/components/ui/input";

export function ContactInput({
  icon,
  label,
  type,
  value,
  onChange,
  required = false,
  maxLength,
  inputMode,
  pattern,
  phoneNormalizer = normalizePhoneNumber,
}: {
  icon: ReactNode;
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  maxLength?: number;
  inputMode?: React.InputHTMLAttributes<HTMLInputElement>["inputMode"];
  pattern?: string;
  phoneNormalizer?: (phone: string) => string | null;
}) {
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const phoneInvalid = type === "tel" && Boolean(value.trim()) && !phoneNormalizer(value);
  return (
    <div className="block min-w-0 space-y-1.5">
      <label htmlFor={inputId} className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</label>
      <div className="relative min-w-0">
        <span className="absolute left-3 top-3 text-slate-400">{icon}</span>
        <Input
          type={type}
          id={inputId}
          ref={(input) => { input?.setCustomValidity(phoneInvalid ? PHONE_FORMAT_HELP : ""); }}
          value={value}
          onChange={(event) => {
            const text = event.target.value;
            event.target.setCustomValidity(type === "tel" && text.trim() && !phoneNormalizer(text) ? PHONE_FORMAT_HELP : "");
            onChange(text);
          }}
          className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-10 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
          required={required}
          maxLength={maxLength ?? (type === "tel" ? 64 : undefined)}
          inputMode={inputMode ?? (type === "tel" ? "tel" : undefined)}
          pattern={pattern}
          aria-invalid={phoneInvalid || undefined}
          aria-describedby={type === "tel" ? hintId : undefined}
        />
      </div>
      {type === "tel" && <span id={hintId} className={`block text-xs normal-case tracking-normal ${phoneInvalid ? "text-red-700" : "text-slate-500"}`}>{PHONE_FORMAT_HELP}</span>}
    </div>
  );
}
