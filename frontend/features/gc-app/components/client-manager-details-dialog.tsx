"use client";

import { KeyRound, LogOut, Pencil, Power, ShieldAlert, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input, PasswordInput, Skeleton } from "@/components/ui";
import {
  useClientManagerAudit,
  useClientManagerMutations,
  useClientManagerSessions,
} from "../hooks/use-gc-app-admin";
import type { ClientManagerAccount } from "../types";
import { formatGcDateTime, gcAppErrorMessage } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

type DetailTab = "overview" | "sessions" | "audit";
type Confirmation = "suspend" | "reactivate" | "revoke" | "delete" | null;

export function ClientManagerDetailsDialog({
  open,
  agencyId,
  manager,
  onClose,
  onEdit,
}: {
  open: boolean;
  agencyId: string | null;
  manager: ClientManagerAccount | null;
  onClose: () => void;
  onEdit: () => void;
}) {
  const [tab, setTab] = useState<DetailTab>("overview");
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [temporaryPassword, setTemporaryPassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const sessions = useClientManagerSessions(agencyId, manager?.id ?? null);
  const audit = useClientManagerAudit(agencyId, manager?.id ?? null);
  const actions = useClientManagerMutations(agencyId);
  const isPending = actions.setStatus.isPending
    || actions.resetPassword.isPending
    || actions.revokeSessions.isPending
    || actions.softDelete.isPending;

  if (!manager) return null;

  const runConfirmation = async () => {
    if (!confirmation) return;
    setError(null);
    try {
      if (confirmation === "suspend") {
        await actions.setStatus.mutateAsync({ managerId: manager.id, status: "suspended", revision: manager.revision });
      } else if (confirmation === "reactivate") {
        await actions.setStatus.mutateAsync({ managerId: manager.id, status: "active", revision: manager.revision });
      } else if (confirmation === "revoke") {
        await actions.revokeSessions.mutateAsync(manager.id);
      } else if (confirmation === "delete") {
        if (deleteConfirmation !== "DELETE") {
          setError("Type DELETE to confirm safe account removal.");
          return;
        }
        await actions.softDelete.mutateAsync(manager.id);
        onClose();
      }
      setConfirmation(null);
      setDeleteConfirmation("");
    } catch (actionError) {
      setError(gcAppErrorMessage(actionError, "The account security action could not be completed."));
    }
  };

  const resetPassword = async () => {
    setError(null);
    if (
      temporaryPassword.length < 10
      || !/[A-Z]/.test(temporaryPassword)
      || !/[a-z]/.test(temporaryPassword)
      || !/\d/.test(temporaryPassword)
    ) {
      setError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }
    try {
      await actions.resetPassword.mutateAsync({ managerId: manager.id, temporaryPassword });
      setTemporaryPassword("");
      setPasswordOpen(false);
    } catch (actionError) {
      setError(gcAppErrorMessage(actionError, "The password could not be reset."));
    }
  };

  return (
    <GcDialog
      open={open}
      title={manager.name}
      description={`${manager.company.name} · ${manager.email}`}
      onClose={onClose}
      closeDisabled={isPending}
      size="xl"
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2" role="tablist" aria-label="Client Manager details">
            {(["overview", "sessions", "audit"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
                className={`min-h-10 rounded-lg px-4 text-sm font-medium capitalize focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 ${
                  tab === value ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                {value}
              </button>
            ))}
          </div>
          <Button type="button" variant="secondary" size="sm" leftIcon={<Pencil className="h-4 w-4" />} onClick={onEdit}>
            Edit account
          </Button>
        </div>

        {tab === "overview" && (
          <div role="tabpanel" className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Detail label="Status"><AccountStatusBadge status={manager.status} /></Detail>
              <Detail label="Mobile number">{manager.phone_number}</Detail>
              <Detail label="Last login">{manager.last_login_at ? formatGcDateTime(manager.last_login_at) : "Never"}</Detail>
              <Detail label="Password change">{manager.force_password_change ? "Required" : "Not required"}</Detail>
            </div>

            <Card>
              <CardContent className="space-y-3 p-5">
                <h3 className="text-sm font-semibold text-slate-900">Assigned groups</h3>
                <div className="flex flex-wrap gap-2">
                  {manager.assigned_groups.length === 0 ? (
                    <p className="text-sm text-slate-500">No groups are assigned.</p>
                  ) : manager.assigned_groups.map((group) => (
                    <Badge key={group.id} variant="secondary">{group.name}</Badge>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="space-y-4 p-5">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900">Account security</h3>
                  <p className="mt-1 text-xs text-slate-500">These actions affect only the Client Manager account. Travel groups and passenger records remain unchanged.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" variant="secondary" size="sm" leftIcon={<KeyRound className="h-4 w-4" />} onClick={() => setPasswordOpen((value) => !value)}>
                    Reset password
                  </Button>
                  <Button type="button" variant="secondary" size="sm" leftIcon={<LogOut className="h-4 w-4" />} onClick={() => setConfirmation("revoke")}>
                    Revoke all sessions
                  </Button>
                  {manager.status === "suspended" ? (
                    <Button type="button" variant="secondary" size="sm" leftIcon={<Power className="h-4 w-4" />} onClick={() => setConfirmation("reactivate")}>
                      Reactivate account
                    </Button>
                  ) : (
                    <Button type="button" variant="secondary" size="sm" leftIcon={<ShieldAlert className="h-4 w-4" />} onClick={() => setConfirmation("suspend")} disabled={manager.status === "deleted"}>
                      Suspend account
                    </Button>
                  )}
                  <Button type="button" variant="danger" size="sm" leftIcon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmation("delete")} disabled={manager.status === "deleted"}>
                    Delete account safely
                  </Button>
                </div>

                {passwordOpen && (
                  <div className="space-y-3 rounded-xl border border-blue-200 bg-blue-50/50 p-4">
                    <PasswordInput
                      label="New temporary password"
                      autoComplete="new-password"
                      value={temporaryPassword}
                      onChange={(event) => setTemporaryPassword(event.target.value)}
                    />
                    <p className="text-xs text-slate-600">Resetting signs the Client Manager out and forces a password change at next login.</p>
                    <div className="flex justify-end gap-2">
                      <Button type="button" variant="secondary" size="sm" onClick={() => setPasswordOpen(false)} disabled={isPending}>Cancel</Button>
                      <Button type="button" size="sm" onClick={() => void resetPassword()} isLoading={actions.resetPassword.isPending}>Reset password</Button>
                    </div>
                  </div>
                )}

                {confirmation && (
                  <div className="space-y-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <p className="text-sm font-medium text-amber-900">{confirmationText(confirmation, manager.name)}</p>
                    {confirmation === "delete" && (
                      <Input
                        label="Type DELETE to confirm"
                        value={deleteConfirmation}
                        onChange={(event) => setDeleteConfirmation(event.target.value)}
                        autoComplete="off"
                      />
                    )}
                    <div className="flex justify-end gap-2">
                      <Button type="button" variant="secondary" size="sm" onClick={() => setConfirmation(null)} disabled={isPending}>Cancel</Button>
                      <Button
                        type="button"
                        variant={confirmation === "delete" ? "danger" : "primary"}
                        size="sm"
                        isLoading={isPending}
                        onClick={() => void runConfirmation()}
                      >
                        Confirm
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

        {tab === "sessions" && (
          <div role="tabpanel" className="space-y-3">
            {sessions.isLoading ? <Skeleton className="h-40 w-full" /> : sessions.isError ? (
              <GcAlert message="Device and session history could not be loaded." />
            ) : sessions.data?.items.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No device sessions recorded.</p>
            ) : sessions.data?.items.map((session) => (
              <Card key={session.id}>
                <CardContent className="grid gap-3 p-4 text-sm sm:grid-cols-4">
                  <Detail label="Device">{session.device_name ?? "Unknown device"}</Detail>
                  <Detail label="Platform">{[session.platform, session.app_version].filter(Boolean).join(" · ") || "Unknown"}</Detail>
                  <Detail label="Last active">{formatGcDateTime(session.last_seen_at)}</Detail>
                  <Detail label="State">{session.revoked_at ? "Revoked" : session.current ? "Current" : "Active"}</Detail>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        {tab === "audit" && (
          <div role="tabpanel" className="space-y-3">
            {audit.isLoading ? <Skeleton className="h-40 w-full" /> : audit.isError ? (
              <GcAlert message="Account audit history could not be loaded." />
            ) : audit.data?.items.length === 0 ? (
              <p className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">No account audit events recorded.</p>
            ) : audit.data?.items.map((event) => (
              <div key={event.id} className="border-l-2 border-blue-200 py-1 pl-4">
                <p className="text-sm font-medium text-slate-800">{event.summary}</p>
                <p className="mt-1 text-xs text-slate-500">{event.actor_name ?? "System"} · {formatGcDateTime(event.created_at)}</p>
              </div>
            ))}
          </div>
        )}

        {error && <GcAlert message={error} />}
      </div>
    </GcDialog>
  );
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <div className="mt-1 text-sm font-medium text-slate-800">{children}</div>
    </div>
  );
}

export function AccountStatusBadge({ status }: { status: ClientManagerAccount["status"] }) {
  const variant = status === "active" ? "success" : status === "invited" ? "secondary" : status === "suspended" ? "warning" : "outline";
  return <Badge variant={variant}>{status.charAt(0).toUpperCase() + status.slice(1)}</Badge>;
}

function confirmationText(confirmation: Exclude<Confirmation, null>, name: string): string {
  if (confirmation === "suspend") return `Suspend ${name}? All active sessions will be denied until reactivation.`;
  if (confirmation === "reactivate") return `Reactivate ${name}'s account with its existing explicit group assignments?`;
  if (confirmation === "revoke") return `Revoke every active session for ${name}? They will need to sign in again.`;
  return `Soft-delete ${name}'s login? Groups, passengers, and operational history will remain intact.`;
}
