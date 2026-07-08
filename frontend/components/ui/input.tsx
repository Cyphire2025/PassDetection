/**
 * Input Component — Light Theme
 */

import * as React from "react";
import { cn } from "@/lib/utils/cn";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  leftAddon?: React.ReactNode;
  rightAddon?: React.ReactNode;
}

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, leftAddon, rightAddon, id, ...props }, ref) => {
    const generatedId = React.useId();
    const inputId = id ?? generatedId;
    const errorId = `${inputId}-error`;
    const hintId  = `${inputId}-hint`;

    return (
      <div className="flex flex-col gap-1.5">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium text-slate-700">
            {label}
            {props.required && <span className="ml-1 text-red-500" aria-hidden="true">*</span>}
          </label>
        )}

        <div className="relative flex items-center">
          {leftAddon && (
            <div className="pointer-events-none absolute left-3 text-slate-400">
              {leftAddon}
            </div>
          )}

          <input
            ref={ref}
            suppressHydrationWarning
            id={inputId}
            aria-describedby={[error && errorId, hint && hintId].filter(Boolean).join(" ") || undefined}
            aria-invalid={!!error}
            className={cn(
              "w-full rounded-lg border bg-white text-slate-900 text-sm",
              "placeholder:text-slate-400",
              "transition-colors duration-150",
              "focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-transparent",
              "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-60",
              error
                ? "border-red-400 focus:ring-red-500"
                : "border-slate-300 hover:border-slate-400",
              leftAddon  ? "pl-9"  : "pl-3",
              rightAddon ? "pr-9"  : "pr-3",
              "py-2 h-9",
              className
            )}
            {...props}
          />

          {rightAddon && (
            <div className="absolute right-3 text-slate-400">{rightAddon}</div>
          )}
        </div>

        {hint && !error && (
          <p id={hintId} className="text-xs text-slate-500">{hint}</p>
        )}
        {error && (
          <p id={errorId} role="alert" className="text-xs text-red-500">{error}</p>
        )}
      </div>
    );
  }
);
Input.displayName = "Input";

export { Input };
