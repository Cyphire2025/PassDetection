"use client";

import {
  forwardRef,
  useEffect,
  useId,
  useState,
  type InputHTMLAttributes,
} from "react";
import { cn } from "@/lib/utils/cn";
import {
  DEFAULT_TRIP_TIMEZONE,
  supportedTripTimeZones,
} from "../utils/trip-timezone";

interface TripTimeZoneFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "list" | "type"
> {
  error?: string;
}

export const TripTimeZoneField = forwardRef<HTMLInputElement, TripTimeZoneFieldProps>(
  function TripTimeZoneField({ error, id, value, defaultValue, className, ...props }, ref) {
    const generatedId = useId();
    const inputId = id ?? generatedId;
    const optionsId = `${inputId}-options`;
    const hintId = `${inputId}-hint`;
    const errorId = `${inputId}-error`;
    const currentValue = typeof value === "string"
      ? value
      : typeof defaultValue === "string"
        ? defaultValue
        : DEFAULT_TRIP_TIMEZONE;
    // Keep the server and first browser render deterministic. The exhaustive
    // runtime list is added only after hydration because ICU datasets can
    // differ between Node.js and the user's browser.
    const [options, setOptions] = useState(() => Array.from(new Set([
      DEFAULT_TRIP_TIMEZONE,
      "UTC",
      currentValue,
    ])).sort((left, right) => left.localeCompare(right)));

    useEffect(() => {
      setOptions(supportedTripTimeZones(currentValue));
    }, [currentValue]);

    return (
      <div className="flex flex-col gap-1.5">
        <label htmlFor={inputId} className="text-sm font-medium text-slate-700">
          Trip timezone
          {props.required && <span className="ml-1 text-red-500" aria-hidden="true">*</span>}
        </label>
        <input
          {...props}
          ref={ref}
          id={inputId}
          type="text"
          list={optionsId}
          value={value}
          defaultValue={defaultValue}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : hintId}
          className={cn(
            "h-9 w-full rounded-lg border bg-white px-3 py-2 text-sm text-slate-900 outline-none transition-colors",
            "focus:border-transparent focus:ring-2 focus:ring-blue-600",
            "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-60",
            error ? "border-red-400 focus:ring-red-500" : "border-slate-300 hover:border-slate-400",
            className,
          )}
        />
        <datalist id={optionsId}>
          {options.map((timeZone) => <option key={timeZone} value={timeZone} />)}
        </datalist>
        {error ? (
          <p id={errorId} role="alert" className="text-xs text-red-500">{error}</p>
        ) : (
          <p id={hintId} className="text-xs text-slate-500">
            Controls mobile countdowns and trip-local schedule times (for example, Asia/Kolkata).
          </p>
        )}
      </div>
    );
  },
);
