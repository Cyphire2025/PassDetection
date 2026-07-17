"use client";

import { useEffect, useRef, useState } from "react";
import { CalendarDays } from "lucide-react";
import { Input, type InputProps } from "@/components/ui/input";
import {
  formatPassportDateForUi,
  isPassportIsoDateWithinRange,
  isValidPassportIsoDate,
  maskPassportDateForUi,
  parsePassportDateFromUi,
} from "@/lib/utils/passport-date";

interface PassportDateInputProps extends Omit<
  InputProps,
  "type" | "value" | "defaultValue" | "onChange" | "min" | "max" | "rightAddon"
> {
  value: string;
  onValueChange: (value: string) => void;
  minIso?: string;
  maxIso?: string;
}

export function PassportDateInput({
  value,
  onValueChange,
  minIso,
  maxIso,
  className,
  error,
  onBlur,
  onFocus,
  ...props
}: PassportDateInputProps) {
  const [displayValue, setDisplayValue] = useState(() =>
    formatPassportDateForUi(value)
  );
  const [wasBlurred, setWasBlurred] = useState(false);
  const isEditing = useRef(false);
  const pickerRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isEditing.current) {
      setDisplayValue(formatPassportDateForUi(value));
    }
  }, [value]);

  const parsedValue = parsePassportDateFromUi(displayValue);
  const hasInvalidValue = Boolean(displayValue) && (
    !parsedValue
    || !isPassportIsoDateWithinRange(parsedValue, minIso, maxIso)
  );
  const localError = wasBlurred && hasInvalidValue
    ? "Enter a valid date as DD/MM/YYYY."
    : undefined;

  const handleTextChange = (nextValue: string) => {
    const masked = maskPassportDateForUi(nextValue);
    setDisplayValue(masked);
    setWasBlurred(false);
    const parsed = parsePassportDateFromUi(masked);
    onValueChange(
      parsed && isPassportIsoDateWithinRange(parsed, minIso, maxIso)
        ? parsed
        : masked,
    );
  };

  const openPicker = () => {
    const picker = pickerRef.current;
    if (!picker) return;
    try {
      if (typeof picker.showPicker === "function") {
        picker.showPicker();
      } else {
        picker.click();
      }
    } catch {
      picker.click();
    }
  };

  return (
    <>
      <Input
        {...props}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        value={displayValue}
        maxLength={10}
        pattern="[0-9]{2}/[0-9]{2}/[0-9]{4}"
        placeholder="DD/MM/YYYY"
        className={className}
        error={error || localError}
        onFocus={(event) => {
          isEditing.current = true;
          onFocus?.(event);
        }}
        onBlur={(event) => {
          isEditing.current = false;
          setWasBlurred(true);
          const parsed = parsePassportDateFromUi(displayValue);
          if (parsed && isPassportIsoDateWithinRange(parsed, minIso, maxIso)) {
            setDisplayValue(formatPassportDateForUi(parsed));
            onValueChange(parsed);
          }
          onBlur?.(event);
        }}
        onChange={(event) => handleTextChange(event.target.value)}
        rightAddon={(
          <button
            type="button"
            className="rounded p-0.5 text-slate-500 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Choose date from calendar"
            onClick={openPicker}
          >
            <CalendarDays className="h-4 w-4" aria-hidden="true" />
          </button>
        )}
      />
      <input
        ref={pickerRef}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        className="sr-only"
        value={isValidPassportIsoDate(value) ? value : ""}
        min={minIso}
        max={maxIso}
        onChange={(event) => {
          const iso = event.target.value;
          if (!iso) {
            setDisplayValue("");
            setWasBlurred(false);
            onValueChange("");
            return;
          }
          if (!isPassportIsoDateWithinRange(iso, minIso, maxIso)) {
            return;
          }
          setDisplayValue(formatPassportDateForUi(iso));
          setWasBlurred(false);
          onValueChange(iso);
        }}
      />
    </>
  );
}
