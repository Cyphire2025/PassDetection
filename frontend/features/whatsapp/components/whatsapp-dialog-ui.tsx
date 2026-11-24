"use client";

import { useModalKeyboardBoundary } from "@/components/ui/modal";

import { X } from "lucide-react";
import { type ReactNode, useId, useRef, useSyncExternalStore } from "react";
import { Card, CardContent } from "@/components/ui";
import { createPortal } from "react-dom";

const subscribeToMount = () => () => undefined;

export { ContactEditor } from "./contact-editor";
export type { ManualContact } from "../types/contacts";

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
  const mounted = useSyncExternalStore(subscribeToMount, () => true, () => false);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const handleDialogKeyDown = useModalKeyboardBoundary({ dialogRef: dialogRef, isOpen: mounted, canClose: !isBusy, onClose });

  if (!mounted) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card
        ref={dialogRef}
        onKeyDown={handleDialogKeyDown}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={isBusy}
        tabIndex={-1}
        className={`w-full shadow-2xl outline-none ${layout === "composer" ? "flex max-h-[94dvh] flex-col overflow-hidden rounded-2xl" : "max-h-[92dvh] overflow-auto"} ${widthClass}`}
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
    </div>,
    document.body,
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
