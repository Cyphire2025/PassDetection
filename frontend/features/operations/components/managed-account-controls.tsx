"use client";

import type React from "react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Check, Copy, KeyRound, LogOut, MoreHorizontal, Power, ShieldCheck, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import { useManagedAccountActions } from "../hooks/use-operations";

export function ManagedAccountControls({
  accountId,
  accountName,
  isActive,
  allowDelete = false,
  deleteLabel,
  deleteDisabled = false,
  allowMfaReset = false,
  onDelete,
}: {
  accountId: string;
  accountName: string;
  isActive: boolean;
  allowDelete?: boolean;
  deleteLabel?: string;
  deleteDisabled?: boolean;
  allowMfaReset?: boolean;
  onDelete?: () => void;
}) {
  const actions = useManagedAccountActions();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [showPasswordDialog, setShowPasswordDialog] = useState(false);
  const [showMfaResetDialog, setShowMfaResetDialog] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [activationToken, setActivationToken] = useState<string | null>(null);
  const [activationCopied, setActivationCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const passwordDialogRef = useRef<HTMLDivElement>(null);
  const mfaDialogRef = useRef<HTMLDivElement>(null);
  const passwordTitleId = useId();
  const passwordDescriptionId = useId();
  const mfaTitleId = useId();
  const mfaDescriptionId = useId();
  const isPending = actions.resetPassword.isPending
    || actions.resetMfa.isPending
    || actions.revokeSessions.isPending
    || actions.setStatus.isPending
    || actions.deleteAccount.isPending;
  const closePasswordDialog = useCallback(() => {
    if (actions.resetPassword.isPending) return;
    setShowPasswordDialog(false);
    setActivationToken(null);
  }, [actions.resetPassword.isPending]);
  const closeMfaDialog = useCallback(() => {
    if (actions.resetMfa.isPending) return;
    setShowMfaResetDialog(false);
  }, [actions.resetMfa.isPending]);
  const handlePasswordDialogKeyDown = useModalKeyboardBoundary({
    dialogRef: passwordDialogRef,
    isOpen: showPasswordDialog,
    canClose: !actions.resetPassword.isPending,
    onClose: closePasswordDialog,
  });
  const handleMfaDialogKeyDown = useModalKeyboardBoundary({
    dialogRef: mfaDialogRef,
    isOpen: showMfaResetDialog,
    canClose: !actions.resetMfa.isPending,
    onClose: closeMfaDialog,
  });

  const resetPassword = async () => {
    setError(null);
    try {
      const updated = await actions.resetPassword.mutateAsync(accountId);
      if (!updated.activation_token) throw new Error("Activation link was not returned");
      setActivationToken(updated.activation_token);
      setActivationCopied(false);
    } catch {
      setError("The credential reset link could not be issued.");
    }
  };

  useEffect(() => {
    if (!showActions || !buttonRef.current) return;

    const updatePosition = () => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const menuWidth = 208;
      const menuHeight = (allowDelete || onDelete ? 180 : 136) + (allowMfaReset ? 44 : 0);
      const gap = 8;
      const hasRoomBelow = window.innerHeight - rect.bottom > menuHeight + gap;
      setMenuPosition({
        left: Math.max(12, Math.min(window.innerWidth - menuWidth - 12, rect.right - menuWidth)),
        top: hasRoomBelow ? rect.bottom + gap : Math.max(12, rect.top - menuHeight - gap),
      });
    };

    updatePosition();
    window.addEventListener("scroll", updatePosition, true);
    window.addEventListener("resize", updatePosition);
    return () => {
      window.removeEventListener("scroll", updatePosition, true);
      window.removeEventListener("resize", updatePosition);
    };
  }, [allowDelete, allowMfaReset, onDelete, showActions]);

  useEffect(() => {
    if (!showActions) return;
    const closeOnOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (buttonRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setShowActions(false);
    };
    document.addEventListener("mousedown", closeOnOutside);
    return () => document.removeEventListener("mousedown", closeOnOutside);
  }, [showActions]);

  return (
    <>
      <div className="flex justify-end">
        <Button
          ref={buttonRef}
          type="button"
          size="icon"
          variant="ghost"
          className="h-8 w-8 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          disabled={isPending}
          onClick={() => setShowActions((current) => !current)}
          aria-label={`Open actions for ${accountName}`}
          aria-expanded={showActions}
          aria-haspopup="menu"
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </Button>

        {showActions && menuPosition && (
          <div
            ref={menuRef}
            role="menu"
            className="fixed z-[80] w-52 overflow-hidden rounded-lg border border-slate-200 bg-white p-1 shadow-2xl shadow-slate-900/15"
            style={{ top: menuPosition.top, left: menuPosition.left }}
          >
            <ActionMenuButton
              icon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
              label="Issue reset link"
              onClick={() => {
                setShowActions(false);
                setActivationToken(null);
                setShowPasswordDialog(true);
              }}
            />
            {allowMfaReset && (
              <ActionMenuButton
                icon={<ShieldCheck className="h-4 w-4" aria-hidden="true" />}
                label="Reset MFA"
                onClick={() => {
                  setShowActions(false);
                  setShowMfaResetDialog(true);
                }}
              />
            )}
            <ActionMenuButton
              icon={<LogOut className="h-4 w-4" aria-hidden="true" />}
              label="Sign out everywhere"
              onClick={() => {
                setShowActions(false);
                actions.revokeSessions.mutate(accountId);
              }}
            />
            <ActionMenuButton
              icon={<Power className="h-4 w-4" aria-hidden="true" />}
              label={isActive ? "Deactivate account" : "Activate account"}
              onClick={() => {
                setShowActions(false);
                actions.setStatus.mutate({ accountId, isActive: !isActive });
              }}
            />
            {(allowDelete || onDelete) && (
              <>
                <div className="my-1 h-px bg-slate-100" />
                <ActionMenuButton
                  danger
                  disabled={deleteDisabled}
                  icon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
                  label={deleteLabel ?? "Delete coordinator"}
                  onClick={() => {
                    setShowActions(false);
                    if (onDelete) {
                      onDelete();
                    } else if (window.confirm(`Permanently remove ${accountName}'s login account? The coordinator will be removed from this list. Required operational history will remain.`)) {
                      setActionError(null);
                      void actions.deleteAccount.mutateAsync(accountId).catch((deleteError: unknown) => {
                        setActionError(getAccountActionError(deleteError));
                      });
                    }
                  }}
                />
              </>
            )}
          </div>
        )}
      </div>

      {actionError && (
        <div
          role="alert"
          className="fixed right-4 top-20 z-[90] flex max-w-sm items-start gap-3 rounded-xl border border-red-200 bg-white px-4 py-3 text-sm text-red-700 shadow-xl"
        >
          <span>{actionError}</span>
          <button
            type="button"
            className="shrink-0 rounded p-0.5 text-red-500 hover:bg-red-50 hover:text-red-800"
            onClick={() => setActionError(null)}
            aria-label="Dismiss account action error"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}

      {showPasswordDialog && (
        <div
          ref={passwordDialogRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby={passwordTitleId}
          aria-describedby={passwordDescriptionId}
          onKeyDown={handlePasswordDialogKeyDown}
        >
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id={passwordTitleId} className="font-semibold text-slate-900">Issue a credential reset link</h2>
                <p id={passwordDescriptionId} className="mt-1 text-sm text-slate-500">This immediately signs {accountName} out everywhere. They choose the replacement password.</p>
              </div>
              <button type="button" onClick={closePasswordDialog} className="text-slate-400 hover:text-slate-700" aria-label="Close credential reset dialog">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-5 space-y-4">
              <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800">The single-use link expires in seven days and is returned only once. Send it through an approved channel.</p>
              {activationToken && (
                <div className="space-y-2">
                  <div className="break-all rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800">{staffActivationLink(activationToken)}</div>
                  <p className="text-xs text-slate-500">Copy this before closing. The dashboard does not store the raw link.</p>
                </div>
              )}
              {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={closePasswordDialog} data-dialog-initial-focus>{activationToken ? "Done" : "Cancel"}</Button>
                {activationToken ? (
                  <Button
                    type="button"
                    leftIcon={activationCopied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
                    onClick={() => {
                      void navigator.clipboard.writeText(staffActivationLink(activationToken)).then(() => setActivationCopied(true));
                    }}
                  >
                    {activationCopied ? "Copied" : "Copy link"}
                  </Button>
                ) : (
                  <Button type="button" isLoading={actions.resetPassword.isPending} onClick={() => void resetPassword()}>
                    Issue reset link
                  </Button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {showMfaResetDialog && (
        <div
          ref={mfaDialogRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby={mfaTitleId}
          aria-describedby={mfaDescriptionId}
          onKeyDown={handleMfaDialogKeyDown}
        >
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
            <h2 id={mfaTitleId} className="font-semibold text-slate-900">Reset MFA for {accountName}?</h2>
            <p id={mfaDescriptionId} className="mt-2 text-sm leading-6 text-slate-600">
              This removes the current authenticator and recovery codes, signs the account out everywhere, and requires fresh MFA enrollment after the next password sign-in.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button type="button" variant="secondary" disabled={actions.resetMfa.isPending} onClick={closeMfaDialog} data-dialog-initial-focus>Cancel</Button>
              <Button
                type="button"
                variant="danger"
                isLoading={actions.resetMfa.isPending}
                onClick={() => {
                  setActionError(null);
                  void actions.resetMfa.mutateAsync(accountId)
                    .then(() => setShowMfaResetDialog(false))
                    .catch((resetError: unknown) => setActionError(getAccountActionError(resetError)));
                }}
              >
                Reset MFA and sign out
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function staffActivationLink(token: string): string {
  if (typeof window === "undefined") return token;
  const url = new URL("/activate", window.location.origin);
  url.searchParams.set("token", token);
  return url.toString();
}

function getAccountActionError(error: unknown): string {
  if (
    typeof error === "object"
    && error !== null
    && "message" in error
    && typeof error.message === "string"
    && error.message.trim()
  ) {
    return error.message;
  }
  return "The account could not be deleted. Please try again.";
}

function ActionMenuButton({
  danger = false,
  disabled = false,
  icon,
  label,
  onClick,
}: {
  danger?: boolean;
  disabled?: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${
        danger
          ? "text-red-700 hover:bg-red-50"
          : "text-slate-700 hover:bg-slate-50 hover:text-slate-950"
      } disabled:pointer-events-none disabled:opacity-50`}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
