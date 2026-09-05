"use client";

import { X } from "lucide-react";
import {
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useEffect,
  useId,
  useRef,
} from "react";
import { Button, Card, CardContent, Input } from "@/components/ui";

export type ManualContact = {
  name: string;
  phone_number: string;
  imported_fields?: Record<string, string>;
};

function importedFieldLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function ContactEditor({
  title,
  description,
  value,
  contacts,
  onValueChange,
  onAdd,
  onRemove,
  onContactChange,
}: {
  title: string;
  description: string;
  value: ManualContact;
  contacts: ManualContact[];
  onValueChange: Dispatch<SetStateAction<ManualContact>>;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onContactChange?: (index: number, contact: ManualContact) => void;
}) {
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4">
      <div>
        <h3 className="font-medium text-slate-900">{title}</h3>
        <p className="mt-1 text-xs text-slate-500">{description}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <Input
          label="Name"
          placeholder="Raman Jha"
          value={value.name}
          onChange={(event) => onValueChange((current) => ({ ...current, name: event.target.value }))}
        />
        <Input
          label="WhatsApp number"
          placeholder="+91 98187 52221"
          value={value.phone_number}
          onChange={(event) => onValueChange((current) => ({ ...current, phone_number: event.target.value }))}
        />
        <div className="flex items-end">
          <Button
            type="button"
            variant="secondary"
            disabled={!value.name.trim() || !value.phone_number.trim()}
            onClick={onAdd}
          >
            Add
          </Button>
        </div>
      </div>
      {contacts.length > 0 && (
        <div className="max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
          {contacts.map((contact, index) => (
            <div
              key={index}
              className={`gap-2 px-3 py-2 text-sm ${
                onContactChange
                  ? "grid items-center md:grid-cols-[1fr_1fr_auto]"
                  : "flex items-center justify-between"
              }`}
            >
              {onContactChange ? (
                <>
                  <Input
                    aria-label={`Recipient ${index + 1} name`}
                    value={contact.name}
                    onChange={(event) =>
                      onContactChange(index, {
                        ...contact,
                        name: event.target.value,
                      })
                    }
                  />
                  <Input
                    aria-label={`Recipient ${index + 1} WhatsApp number`}
                    value={contact.phone_number}
                    onChange={(event) =>
                      onContactChange(index, {
                        ...contact,
                        phone_number: event.target.value,
                      })
                    }
                  />
                </>
              ) : (
                <span className="min-w-0 truncate text-slate-700">
                  {contact.name} - {contact.phone_number}
                </span>
              )}
              <button
                type="button"
                className="justify-self-end text-xs font-medium text-red-600 hover:text-red-700"
                onClick={() => onRemove(index)}
                aria-label={`Remove ${contact.name || `contact ${index + 1}`}`}
              >
                Remove
              </button>
              {contact.imported_fields &&
                Object.keys(contact.imported_fields).length > 0 && (
                  <details className="md:col-span-3">
                    <summary className="cursor-pointer text-xs font-medium text-blue-700">
                      View {Object.keys(contact.imported_fields).length} imported
                      detail
                      {Object.keys(contact.imported_fields).length === 1
                        ? ""
                        : "s"}
                    </summary>
                    <dl className="mt-2 grid gap-x-4 gap-y-2 rounded-lg bg-slate-50 p-3 sm:grid-cols-2">
                      {Object.entries(contact.imported_fields).map(
                        ([key, fieldValue]) => (
                          <div key={key} className="min-w-0">
                            <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                              {importedFieldLabel(key)}
                            </dt>
                            <dd className="truncate text-xs text-slate-700">
                              {fieldValue}
                            </dd>
                          </div>
                        ),
                      )}
                    </dl>
                  </details>
                )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function DialogFrame({
  title,
  onClose,
  isBusy = false,
  widthClass = "max-w-3xl",
  layout = "default",
  description,
  eyebrow,
  children,
}: {
  title: string;
  onClose: () => void;
  isBusy?: boolean;
  widthClass?: string;
  layout?: "default" | "composer";
  description?: string;
  eyebrow?: string;
  children: ReactNode;
}) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const isBusyRef = useRef(isBusy);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    isBusyRef.current = isBusy;
    onCloseRef.current = onClose;
  }, [isBusy, onClose]);

  useEffect(() => {
    const previousFocus = document.activeElement;
    const dialog = dialogRef.current;
    dialog?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!isBusyRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      if (
        document.activeElement !== dialog
        && !dialog.contains(document.activeElement)
      ) return;

      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
        ),
      ).filter((element) => !element.hasAttribute("hidden"));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
    };
  }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isBusy}
        tabIndex={-1}
        className={`w-full shadow-2xl outline-none ${layout === "composer" ? "flex max-h-[94dvh] flex-col overflow-hidden rounded-2xl" : "max-h-[92vh] overflow-auto"} ${widthClass}`}
      >
        <CardContent className={layout === "composer" ? "flex min-h-0 flex-1 flex-col p-0" : "p-6"}>
          <div className={`flex shrink-0 items-start justify-between gap-4 ${layout === "composer" ? "border-b border-slate-200 px-5 py-4 sm:px-7 sm:py-5" : "mb-5"}`}>
            <div className="min-w-0">
              {eyebrow && <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{eyebrow}</p>}
              <h2 id={titleId} className={`text-lg font-semibold text-slate-900 ${layout === "composer" ? "tracking-tight sm:text-xl" : ""}`}>{title}</h2>
              {description && <p className="mt-1 break-words text-sm text-slate-500">{description}</p>}
            </div>
            <button
              type="button"
              className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              onClick={onClose}
              disabled={isBusy}
              aria-label="Close dialog"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {children}
        </CardContent>
      </Card>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
    >
      {message}
    </div>
  );
}

export function readErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "response" in error) {
    const response = (error as {
      response?: { data?: { detail?: unknown; message?: unknown } };
    }).response;
    const detail = response?.data?.detail ?? response?.data?.message;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => (
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : ""
        ))
        .filter(Boolean);
      if (messages.length > 0) return messages.join(" ");
    }
  }
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
