"use client";

import { useCallback, useId, useRef, useState } from "react";
import { CalendarClock, Loader2, ShieldCheck, ShieldOff, X } from "lucide-react";
import { Button, Card, CardContent } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { UserRole } from "@/types/auth.types";
import {
  usePassportRetention,
  useUpdatePassportRetention,
} from "../hooks/use-passport-retention";

interface PassportRetentionControlProps {
  groupId: string;
  groupName: string;
  allowed?: boolean;
  enabled?: boolean;
}

export function canManagePassportRetention(role: UserRole | null | undefined): boolean {
  return role === "super_admin" || role === "agency_admin";
}

export function PassportRetentionControl({
  groupId,
  groupName,
  allowed = true,
  enabled = true,
}: PassportRetentionControlProps) {
  const { data, isLoading, error } = usePassportRetention(groupId, allowed && enabled);
  const update = useUpdatePassportRetention(groupId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const nextLegalHold = !data?.legal_hold;

  const closeDialog = useCallback(() => {
    if (update.isPending) return;
    setDialogOpen(false);
    setReason("");
    update.reset();
  }, [update]);

  const submit = () => {
    const normalizedReason = reason.trim().replace(/\s+/g, " ");
    if (normalizedReason.length < 3) return;
    update.mutate(
      { legalHold: nextLegalHold, reason: normalizedReason },
      {
        onSuccess: (retention) => {
          setNotice(
            retention.legal_hold
              ? "Legal hold placed. Automated passport deletion is paused for this group."
              : "Legal hold released. The explicit retention schedule is active again.",
          );
          setDialogOpen(false);
          setReason("");
        },
      },
    );
  };

  if (!allowed || !enabled) return null;

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span
              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                data?.legal_hold
                  ? "bg-amber-100 text-amber-700"
                  : "bg-emerald-50 text-emerald-700"
              }`}
              aria-hidden="true"
            >
              {data?.legal_hold ? <ShieldCheck className="h-5 w-5" /> : <CalendarClock className="h-5 w-5" />}
            </span>
            <div className="min-w-0">
              <h2 className="text-base font-semibold text-slate-900">Passport retention &amp; legal hold</h2>
              <p className="mt-1 text-sm leading-6 text-slate-600">
                Review the explicit deletion schedule and pause automated deletion when a documented legal or operational obligation applies.
              </p>
            </div>
          </div>

          {data && (
            <Button
              type="button"
              variant={data.legal_hold ? "secondary" : "outline"}
              onClick={() => {
                setNotice(null);
                update.reset();
                setDialogOpen(true);
              }}
              leftIcon={data.legal_hold ? <ShieldOff className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}
            >
              {data.legal_hold ? "Release legal hold" : "Place legal hold"}
            </Button>
          )}
        </div>

        {isLoading && (
          <div className="mt-4 flex items-center gap-2 text-sm text-slate-600" role="status">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading retention schedule
          </div>
        )}

        {error && (
          <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">
            {errorMessage(error, "The retention schedule could not be loaded.")}
          </p>
        )}

        {data && (
          <dl className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm sm:grid-cols-2 xl:grid-cols-3">
            <RetentionValue label="Status" value={data.legal_hold ? "Legal hold active" : "Scheduled retention active"} />
            <RetentionValue label="Explicit purge date" value={formatRetentionDate(data.passport_purge_at)} />
            <RetentionValue
              label="Retention policy applied"
              value={data.passport_retention_days_applied === null
                ? "Not yet scheduled"
                : `${data.passport_retention_days_applied.toLocaleString()} days`}
            />
            {data.legal_hold && (
              <>
                <RetentionValue label="Hold reason" value={data.legal_hold_reason ?? "Reason unavailable"} />
                <RetentionValue label="Hold placed" value={formatRetentionDate(data.legal_hold_set_at)} />
              </>
            )}
          </dl>
        )}

        {notice && (
          <p className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800" role="status" aria-live="polite">
            {notice}
          </p>
        )}
      </CardContent>

      <RetentionReasonDialog
        open={dialogOpen}
        groupName={groupName}
        placingHold={nextLegalHold}
        reason={reason}
        error={update.error}
        isSubmitting={update.isPending}
        onReasonChange={setReason}
        onClose={closeDialog}
        onConfirm={submit}
      />
    </Card>
  );
}

function RetentionReasonDialog({
  open,
  groupName,
  placingHold,
  reason,
  error,
  isSubmitting,
  onReasonChange,
  onClose,
  onConfirm,
}: {
  open: boolean;
  groupName: string;
  placingHold: boolean;
  reason: string;
  error: unknown;
  isSubmitting: boolean;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const reasonId = useId();
  const errorId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const onDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: open,
    canClose: !isSubmitting,
    onClose,
  });
  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-950/55 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={`${descriptionId}${error ? ` ${errorId}` : ""}`}
      onKeyDown={onDialogKeyDown}
    >
      <div className="w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <h2 id={titleId} className="text-lg font-semibold text-slate-950">
              {placingHold ? "Place passport legal hold" : "Release passport legal hold"}
            </h2>
            <p id={descriptionId} className="mt-1 text-sm leading-6 text-slate-600">
              {placingHold
                ? `Automated passport deletion for ${groupName} will pause until an administrator releases the hold.`
                : `Passport deletion for ${groupName} will resume according to its explicit purge schedule.`}
              {" "}A meaningful reason is required and will be written to the audit log.
            </p>
          </div>
          <button
            type="button"
            className="rounded-full p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
            aria-label="Close retention control"
            disabled={isSubmitting}
            onClick={onClose}
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="space-y-2 px-6 py-5">
          <label htmlFor={reasonId} className="block text-sm font-medium text-slate-800">
            Audit reason
          </label>
          <textarea
            id={reasonId}
            value={reason}
            minLength={3}
            maxLength={500}
            rows={4}
            required
            data-dialog-initial-focus
            aria-invalid={Boolean(error)}
            aria-describedby={error ? errorId : undefined}
            className="w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/20"
            placeholder={placingHold ? "Example: Active legal discovery request" : "Example: Legal review completed and release approved"}
            onChange={(event) => onReasonChange(event.target.value)}
          />
          <p className="text-xs text-slate-500">Use 3–500 characters.</p>
          {Boolean(error) && (
            <p id={errorId} className="text-sm text-red-700" role="alert">
              {errorMessage(error, "The legal-hold update could not be saved.")}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            type="button"
            variant={placingHold ? "primary" : "danger"}
            isLoading={isSubmitting}
            disabled={reason.trim().replace(/\s+/g, " ").length < 3}
            onClick={onConfirm}
          >
            {placingHold ? "Place legal hold" : "Release legal hold"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function RetentionValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-1 break-words font-medium text-slate-900">{value}</dd>
    </div>
  );
}

function formatRetentionDate(value: string | null): string {
  if (!value) return "Not yet scheduled";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Schedule unavailable";
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
