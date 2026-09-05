"use client";

import { FormEvent, useId, useRef, useState } from "react";
import { Check, Copy, Plus, ShieldCheck, UserPlus, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import {
  useAdminGroups,
  useAssignStaffGroups,
  useCreateStaff,
  useStaffAccessAccounts,
} from "../hooks/use-operations";
import { ManagedAccountControls } from "./managed-account-controls";
import type { ManagerGroupAccess, StaffAccount } from "../api/operations.api";
import { useModalKeyboardBoundary } from "@/components/ui/modal";

type StaffForm = {
  full_name: string;
  email: string;
};

export function ManagedAccountsPanel() {
  const { data: staffAccounts = [], isLoading, error } = useStaffAccessAccounts();
  const { data: groups = [] } = useAdminGroups();
  const createStaff = useCreateStaff();
  const assignStaffGroups = useAssignStaffGroups();
  const [showCreateStaff, setShowCreateStaff] = useState(false);
  const [staffForm, setStaffForm] = useState<StaffForm>({ full_name: "", email: "" });
  const [staffFormError, setStaffFormError] = useState<string | null>(null);
  const [staffAccessError, setStaffAccessError] = useState<{ staffId: string; message: string } | null>(null);
  const [issuedInvitation, setIssuedInvitation] = useState<{ name: string; token: string } | null>(null);
  const [invitationCopied, setInvitationCopied] = useState(false);
  const createStaffButtonRef = useRef<HTMLButtonElement>(null);
  const invitationDialogRef = useRef<HTMLDivElement>(null);
  const invitationTitleId = useId();
  const invitationDescriptionId = useId();
  const closeInvitation = () => {
    setIssuedInvitation(null);
    window.requestAnimationFrame(() => createStaffButtonRef.current?.focus());
  };
  const handleInvitationKeyDown = useModalKeyboardBoundary({
    dialogRef: invitationDialogRef,
    isOpen: Boolean(issuedInvitation),
    canClose: true,
    onClose: closeInvitation,
  });

  const handleCreateStaff = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setStaffFormError(null);
    try {
      const created = await createStaff.mutateAsync(staffForm);
      if (!created.activation_token) throw new Error("Activation link was not returned");
      setIssuedInvitation({ name: created.full_name, token: created.activation_token });
      setInvitationCopied(false);
      setStaffForm({ full_name: "", email: "" });
      setShowCreateStaff(false);
    } catch {
      setStaffFormError("Could not create staff. Check whether the email already exists.");
    }
  };

  const updateStaffGroups = async (staffId: string, groupIds: string[]) => {
    setStaffAccessError(null);
    try {
      await assignStaffGroups.mutateAsync({ staffId, groupIds });
    } catch (assignmentError) {
      setStaffAccessError({
        staffId,
        message: getStaffAccessError(assignmentError),
      });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <WorkspacePageHeader
        icon={ShieldCheck}
        title="Staff"
        description="Create and manage staff accounts."
        actions={(
          <Button ref={createStaffButtonRef} type="button" onClick={() => setShowCreateStaff(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Create Staff
          </Button>
        )}
      />

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 p-5">
            <div>
              <h2 className="font-semibold text-slate-900">Staff Accounts</h2>
              <p className="mt-1 text-sm text-slate-500">Normal office employees. Their feature access can be decided separately from managers and coordinators.</p>
            </div>
            <Badge variant="secondary" className="px-3 py-1">{staffAccounts.length} total</Badge>
          </div>
          {error ? (
            <p className="p-5 text-sm text-red-700">Staff accounts could not be loaded.</p>
          ) : isLoading ? (
            <div className="space-y-3 p-5"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
          ) : staffAccounts.length === 0 ? (
            <p className="p-5 text-sm text-slate-500">No staff accounts created yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] table-fixed text-left text-sm">
                <colgroup>
                  <col className="w-[26%]" />
                  <col className="w-[34%]" />
                  <col className="w-[16%]" />
                  <col className="w-[12%]" />
                  <col className="w-[12%]" />
                </colgroup>
                <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr><th className="px-5 py-3">Staff</th><th className="px-5 py-3">Access</th><th className="px-5 py-3">Last login</th><th className="px-5 py-3">Status</th><th className="px-5 py-3 text-right">Actions</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {staffAccounts.map((account) => (
                    <tr key={account.id}>
                      <td className="px-5 py-4"><div className="font-medium text-slate-900">{account.full_name}</div><div className="text-xs text-slate-500">{account.email}</div></td>
                      <td className="px-5 py-4">
                        <StaffAccessControl
                          staff={account}
                          groups={groups}
                          disabled={assignStaffGroups.isPending}
                          error={staffAccessError?.staffId === account.id ? staffAccessError.message : null}
                          onAssign={(groupId) => {
                            const assignedIds = account.assigned_groups.map((group) => group.id);
                            void updateStaffGroups(account.id, [...assignedIds, groupId]);
                          }}
                          onRemove={(groupId) => {
                            void updateStaffGroups(
                              account.id,
                              account.assigned_groups
                                .map((group) => group.id)
                                .filter((assignedId) => assignedId !== groupId),
                            );
                          }}
                        />
                      </td>
                      <td className="px-5 py-4 text-slate-600">{account.last_login_at ? formatDateTime(account.last_login_at) : "Never"}</td>
                      <td className="px-5 py-4"><Badge variant={account.is_active ? "success" : "outline"}>{account.is_active ? "Active" : "Inactive"}</Badge></td>
                      <td className="px-5 py-4">
                        <ManagedAccountControls
                          accountId={account.id}
                          accountName={account.full_name}
                          isActive={account.is_active}
                          allowMfaReset
                          allowDelete
                          deleteLabel="Delete staff"
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {showCreateStaff && (
        <CreateStaffDialog
          form={staffForm}
          formError={staffFormError}
          isLoading={createStaff.isPending}
          onClose={() => {
            setShowCreateStaff(false);
            setStaffFormError(null);
          }}
          onFormChange={setStaffForm}
          onSubmit={handleCreateStaff}
        />
      )}

      {issuedInvitation && (
        <div
          ref={invitationDialogRef}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-labelledby={invitationTitleId}
          aria-describedby={invitationDescriptionId}
          onKeyDown={handleInvitationKeyDown}
        >
          <Card className="w-full max-w-lg shadow-2xl">
            <CardContent className="space-y-4 p-6">
              <div>
                <h2 id={invitationTitleId} className="font-semibold text-slate-950">Staff activation link created</h2>
                <p id={invitationDescriptionId} className="mt-1 text-sm leading-6 text-slate-600">{issuedInvitation.name} must use this single-use link within seven days and choose their own password. The raw link is not stored in the dashboard.</p>
              </div>
              <div className="break-all rounded-xl border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800">{staffActivationLink(issuedInvitation.token)}</div>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  data-dialog-initial-focus
                  leftIcon={invitationCopied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
                  onClick={() => {
                    void navigator.clipboard.writeText(staffActivationLink(issuedInvitation.token)).then(() => setInvitationCopied(true));
                  }}
                >
                  {invitationCopied ? "Copied" : "Copy activation link"}
                </Button>
                <Button type="button" onClick={closeInvitation}>Done</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

function StaffAccessControl({
  staff,
  groups,
  disabled,
  error,
  onAssign,
  onRemove,
}: {
  staff: StaffAccount;
  groups: ManagerGroupAccess[];
  disabled: boolean;
  error: string | null;
  onAssign: (groupId: string) => void;
  onRemove: (groupId: string) => void;
}) {
  const createdIds = new Set(staff.created_groups.map((group) => group.id));
  const assignedIds = new Set(staff.assigned_groups.map((group) => group.id));
  const assignableGroups = groups.filter((group) =>
    group.agency_id === staff.agency_id
    && group.status !== "archived"
    && group.status !== "deleted"
    && !createdIds.has(group.id)
    && !assignedIds.has(group.id),
  );

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          <ShieldCheck className="h-3.5 w-3.5" />
          Own groups ({staff.created_groups.length})
        </span>
        {staff.assigned_groups.map((group) => (
          <span
            key={group.id}
            className="inline-flex items-center gap-1.5 rounded-full border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"
          >
            {group.name}
            <button
              type="button"
              className="rounded-full text-emerald-700 hover:bg-emerald-100 disabled:opacity-50"
              aria-label={`Remove ${group.name} access`}
              disabled={disabled}
              onClick={() => onRemove(group.id)}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <select
        className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-400"
        disabled={disabled || assignableGroups.length === 0}
        value=""
        onChange={(event) => {
          if (event.target.value) onAssign(event.target.value);
        }}
      >
        <option value="">{assignableGroups.length ? "Assign another group" : "No more groups to assign"}</option>
        {assignableGroups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.name}
          </option>
        ))}
      </select>
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
}

function getStaffAccessError(error: unknown): string {
  if (
    typeof error === "object"
    && error !== null
    && "message" in error
    && typeof error.message === "string"
    && error.message.trim()
  ) {
    return error.message;
  }
  return "Group access could not be updated. Please try again.";
}

function CreateStaffDialog({
  form,
  formError,
  isLoading,
  onClose,
  onFormChange,
  onSubmit,
}: {
  form: StaffForm;
  formError: string | null;
  isLoading: boolean;
  onClose: () => void;
  onFormChange: React.Dispatch<React.SetStateAction<StaffForm>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const handleDialogKeyDown = useModalKeyboardBoundary({
    dialogRef,
    isOpen: true,
    canClose: !isLoading,
    onClose,
  });
  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onKeyDown={handleDialogKeyDown}
    >
      <Card className="w-full max-w-lg overflow-hidden shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                <UserPlus className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2 id={titleId} className="text-base font-semibold text-slate-900">Create Staff</h2>
                <p id={descriptionId} className="mt-0.5 text-sm leading-5 text-slate-500">Staff accounts are separated from managers. Feature access can be assigned later.</p>
              </div>
            </div>
            <button type="button" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose}>
              <X className="h-5 w-5" />
              <span className="sr-only">Close</span>
            </button>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            <Input
              label="Full name"
              placeholder="Example: Priya Sharma"
              value={form.full_name}
              onChange={(event) => onFormChange((current) => ({ ...current, full_name: event.target.value }))}
              required
              data-dialog-initial-focus
            />
            <Input
              label="Email"
              type="email"
              placeholder="staff@company.com"
              value={form.email}
              onChange={(event) => onFormChange((current) => ({ ...current, email: event.target.value }))}
              required
            />
            <p className="rounded-lg border border-blue-200 bg-blue-50 p-3 text-xs leading-5 text-blue-800">A single-use activation link will be shown once after creation. The staff member sets their own password and enrolls MFA before receiving a dashboard session.</p>
            {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
            <div className="flex justify-end gap-3 pt-1">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>
                Create Staff
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function staffActivationLink(token: string): string {
  if (typeof window === "undefined") return token;
  const url = new URL("/activate", window.location.origin);
  url.searchParams.set("token", token);
  return url.toString();
}
