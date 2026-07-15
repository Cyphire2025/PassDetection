"use client";

import type React from "react";
import { useEffect, useRef, useState } from "react";
import { KeyRound, LogOut, MoreHorizontal, Power, Trash2, X } from "lucide-react";
import { Button, PasswordInput } from "@/components/ui";
import { useManagedAccountActions } from "../hooks/use-operations";

export function ManagedAccountControls({
  accountId,
  accountName,
  isActive,
  allowDelete = false,
  deleteLabel,
  deleteDisabled = false,
  onDelete,
}: {
  accountId: string;
  accountName: string;
  isActive: boolean;
  allowDelete?: boolean;
  deleteLabel?: string;
  deleteDisabled?: boolean;
  onDelete?: () => void;
}) {
  const actions = useManagedAccountActions();
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [showPasswordDialog, setShowPasswordDialog] = useState(false);
  const [showActions, setShowActions] = useState(false);
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const isPending = actions.resetPassword.isPending
    || actions.revokeSessions.isPending
    || actions.setStatus.isPending
    || actions.deleteAccount.isPending;

  const resetPassword = async () => {
    setError(null);
    if (password.length < 10 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/\d/.test(password)) {
      setError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }
    try {
      await actions.resetPassword.mutateAsync({ accountId, password });
      setPassword("");
      setShowPasswordDialog(false);
    } catch {
      setError("Password could not be changed.");
    }
  };

  useEffect(() => {
    if (!showActions || !buttonRef.current) return;

    const updatePosition = () => {
      const rect = buttonRef.current?.getBoundingClientRect();
      if (!rect) return;
      const menuWidth = 208;
      const menuHeight = allowDelete || onDelete ? 180 : 136;
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
  }, [allowDelete, onDelete, showActions]);

  useEffect(() => {
    if (!showActions) return;
    const closeOnOutside = (event: MouseEvent) => {
      if (buttonRef.current?.contains(event.target as Node)) return;
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
        >
          <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
        </Button>

        {showActions && menuPosition && (
          <div
            className="fixed z-[80] w-52 overflow-hidden rounded-lg border border-slate-200 bg-white p-1 shadow-2xl shadow-slate-900/15"
            style={{ top: menuPosition.top, left: menuPosition.left }}
          >
            <ActionMenuButton
              icon={<KeyRound className="h-4 w-4" aria-hidden="true" />}
              label="Change password"
              onClick={() => {
                setShowActions(false);
                setShowPasswordDialog(true);
              }}
            />
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
                    } else if (window.confirm(`Remove ${accountName}'s account? Related operational history will be preserved where required.`)) {
                      actions.deleteAccount.mutate(accountId);
                    }
                  }}
                />
              </>
            )}
          </div>
        )}
      </div>

      {showPasswordDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold text-slate-900">Set a new password</h2>
                <p className="mt-1 text-sm text-slate-500">This immediately signs {accountName} out on every device.</p>
              </div>
              <button type="button" onClick={() => setShowPasswordDialog(false)} className="text-slate-400 hover:text-slate-700">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="mt-5 space-y-4">
              <PasswordInput
                label="New password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <p className="text-xs text-slate-500">Minimum 10 characters, including uppercase, lowercase, and a number.</p>
              {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setShowPasswordDialog(false)}>Cancel</Button>
                <Button type="button" isLoading={actions.resetPassword.isPending} onClick={() => void resetPassword()}>
                  Change password
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
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
