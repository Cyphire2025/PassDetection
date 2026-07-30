"use client";

import { X } from "lucide-react";
import {
  type ReactNode,
  useEffect,
  useId,
  useRef,
} from "react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import type { BadgeProps } from "@/components/ui";
import {
  emailStatusVariant,
  formatEmailLabel,
} from "../utils/email-integrations";

export function EmailStatusBadge({
  status,
}: {
  status: string | null | undefined;
}) {
  return (
    <Badge variant={emailStatusVariant(status)} dot>
      {formatEmailLabel(status)}
    </Badge>
  );
}

export function EmailNotice({
  tone,
  children,
}: {
  tone: "success" | "error" | "warning" | "info";
  children: ReactNode;
}) {
  const styles = {
    success: "border-green-200 bg-green-50 text-green-800",
    error: "border-red-200 bg-red-50 text-red-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    info: "border-blue-200 bg-blue-50 text-blue-800",
  }[tone];
  const role = tone === "error" ? "alert" : "status";

  return (
    <div
      role={role}
      aria-live={tone === "error" ? "assertive" : "polite"}
      className={`rounded-lg border px-4 py-3 text-sm ${styles}`}
    >
      {children}
    </div>
  );
}

export function EmailQueryError({
  title = "Email integration data could not be loaded.",
  onRetry,
}: {
  title?: string;
  onRetry: () => void;
}) {
  return (
    <Card className="border-red-200">
      <CardContent className="flex flex-col items-start gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
        <p role="alert" className="text-sm text-red-700">
          {title} Please try again.
        </p>
        <Button type="button" variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </CardContent>
    </Card>
  );
}

export function EmailCardSkeletons({ count = 3 }: { count?: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2" aria-label="Loading email data">
      {Array.from({ length: count }, (_, index) => (
        <Card key={index}>
          <CardContent className="space-y-4 p-5">
            <div className="flex justify-between gap-4">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-5 w-20" />
            </div>
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-16 w-full" />
            <div className="flex gap-2">
              <Skeleton className="h-8 w-24" />
              <Skeleton className="h-8 w-24" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function EmailDialog({
  title,
  description,
  isBusy = false,
  onClose,
  children,
}: {
  title: string;
  description?: string;
  isBusy?: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  const titleId = useId();
  const descriptionId = useId();
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

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        if (!isBusyRef.current) onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;

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
      if (
        event.shiftKey
        && (
          document.activeElement === first
          || document.activeElement === dialog
        )
      ) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

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
        aria-describedby={description ? descriptionId : undefined}
        aria-busy={isBusy}
        tabIndex={-1}
        className="max-h-[92vh] w-full max-w-2xl overflow-auto shadow-2xl outline-none"
      >
        <CardContent className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 id={titleId} className="text-lg font-semibold text-slate-900">
                {title}
              </h2>
              {description && (
                <p id={descriptionId} className="mt-1 text-sm text-slate-600">
                  {description}
                </p>
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={onClose}
              disabled={isBusy}
              aria-label="Close dialog"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          <div className="mt-5">{children}</div>
        </CardContent>
      </Card>
    </div>
  );
}

export function Definition({
  term,
  children,
}: {
  term: string;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {term}
      </dt>
      <dd className="mt-1 break-words text-sm text-slate-800">{children}</dd>
    </div>
  );
}

export type EmailStatusVariant = BadgeProps["variant"];
