"use client";

import { FormEvent, useState } from "react";
import { ShieldCheck, Trash2, UserPlus, Users, X } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import {
  useAdminGroups,
  useAssignManagerGroups,
  useCreateManager,
  useDeleteManager,
  useManagers,
} from "@/features/operations/hooks/use-operations";
import type { ManagerAccount, ManagerGroupAccess } from "@/features/operations/api/operations.api";

export default function AdminPage() {
  const { data: managers = [], isLoading, error } = useManagers();
  const { data: groups = [] } = useAdminGroups();
  const role = useAuthStore(selectUserRole);
  const canDeleteManagers = role === "super_admin";
  const createManager = useCreateManager();
  const assignManagerGroups = useAssignManagerGroups();
  const deleteManager = useDeleteManager();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [managerDeleteTarget, setManagerDeleteTarget] = useState<ManagerAccount | null>(null);
  const [deleteOwnedData, setDeleteOwnedData] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    if (form.password.length < 8) {
      setFormError("Password must be at least 8 characters.");
      return;
    }

    try {
      await createManager.mutateAsync(form);
      setForm({ full_name: "", email: "", password: "" });
    } catch {
      setFormError("Could not create manager. Check whether the email already exists.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Admin"
        description="Create manager accounts and control who can work on group submissions."
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Manager administration is unavailable for this account.
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <UserPlus className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Create Manager</h2>
                <p className="text-sm text-slate-500">Managers can create groups and work on assigned groups.</p>
              </div>
            </div>

            <form className="space-y-4" onSubmit={handleSubmit}>
              <Input
                label="Full name"
                value={form.full_name}
                onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                required
              />
              <Input
                label="Email"
                type="email"
                value={form.email}
                onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                required
              />
              <Input
                label="Temporary password"
                type="password"
                value={form.password}
                onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                required
              />
              {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
              <Button type="submit" className="w-full" disabled={createManager.isPending}>
                {createManager.isPending ? "Creating Manager" : "Create Manager"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardContent className="p-0">
            <div className="flex items-center justify-between border-b border-slate-200 p-5">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <Users className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Managers</h2>
                  <p className="text-sm text-slate-500">Managers automatically keep access to groups they create.</p>
                </div>
              </div>
              <Badge variant="secondary">{managers.length}</Badge>
            </div>

            {isLoading ? (
              <div className="space-y-3 p-5">
                <Skeleton className="h-12 w-full rounded-lg" />
                <Skeleton className="h-12 w-full rounded-lg" />
                <Skeleton className="h-12 w-full rounded-lg" />
              </div>
            ) : managers.length === 0 ? (
              <div className="px-5 py-10 text-sm text-slate-500">No managers created yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1080px] text-left text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="w-[16%] px-5 py-3">Name</th>
                      <th className="w-[25%] px-5 py-3">Email</th>
                      <th className="w-[30%] px-5 py-3">Access</th>
                      <th className="w-[12%] px-5 py-3">Created</th>
                      <th className="w-[11%] px-5 py-3">Last Login</th>
                      <th className="w-[6%] px-5 py-3 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {managers.map((manager) => (
                      <tr key={manager.id} className="hover:bg-slate-50/70">
                        <td className="px-5 py-4 font-medium text-slate-900">{manager.full_name}</td>
                        <td className="px-5 py-4 text-slate-600">{manager.email}</td>
                        <td className="px-5 py-4">
                          <ManagerAccessControl
                            manager={manager}
                            groups={groups}
                            disabled={assignManagerGroups.isPending}
                            onAssign={(groupId) => {
                              const assignedIds = manager.assigned_groups.map((group) => group.id);
                              assignManagerGroups.mutate({ managerId: manager.id, groupIds: [...assignedIds, groupId] });
                            }}
                            onRemove={(groupId) => {
                              assignManagerGroups.mutate({
                                managerId: manager.id,
                                groupIds: manager.assigned_groups
                                  .map((group) => group.id)
                                  .filter((assignedId) => assignedId !== groupId),
                              });
                            }}
                          />
                        </td>
                        <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDateTime(manager.created_at)}</td>
                        <td className="whitespace-nowrap px-5 py-4 text-slate-600">
                          {manager.last_login_at ? formatDateTime(manager.last_login_at) : "Never"}
                        </td>
                        <td className="px-5 py-4 text-right">
                          {canDeleteManagers && (
                            <Button
                              type="button"
                              variant="danger"
                              size="sm"
                              disabled={deleteManager.isPending}
                              onClick={() => {
                                setDeleteOwnedData(false);
                                setManagerDeleteTarget(manager);
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              Delete
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <DeleteManagerDialog
        manager={managerDeleteTarget}
        deleteOwnedData={deleteOwnedData}
        isLoading={deleteManager.isPending}
        onDeleteOwnedDataChange={setDeleteOwnedData}
        onClose={() => setManagerDeleteTarget(null)}
        onConfirm={() => {
          if (!managerDeleteTarget) return;
          deleteManager.mutate(
            { managerId: managerDeleteTarget.id, deleteOwnedData },
            { onSuccess: () => setManagerDeleteTarget(null) },
          );
        }}
      />
    </div>
  );
}

function DeleteManagerDialog({
  manager,
  deleteOwnedData,
  isLoading,
  onDeleteOwnedDataChange,
  onClose,
  onConfirm,
}: {
  manager: ManagerAccount | null;
  deleteOwnedData: boolean;
  isLoading: boolean;
  onDeleteOwnedDataChange: (value: boolean) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  if (!manager) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4 backdrop-blur-sm">
      <div className="w-full max-w-xl overflow-hidden rounded-xl bg-white shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="border-b border-slate-100 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Delete Manager Account</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            This will remove the sign-in access for {manager.full_name}. By default, groups and passport records created by
            this manager are retained under administrator ownership and can be reassigned later.
          </p>
        </div>
        <div className="space-y-4 px-6 py-5">
          <label className="flex gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-900">
            <input
              type="checkbox"
              className="mt-1 h-4 w-4 rounded border-red-300 text-red-600 focus:ring-red-500"
              checked={deleteOwnedData}
              onChange={(event) => onDeleteOwnedDataChange(event.target.checked)}
            />
            <span>
              <span className="block font-semibold">Also permanently delete manager-owned operational data</span>
              <span className="mt-1 block text-red-800">
                Deletes groups, passport submissions, uploaded images, and processing records originally created by this
                manager. This cannot be undone.
              </span>
            </span>
          </label>
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-100 px-6 py-4">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button type="button" variant="danger" onClick={onConfirm} isLoading={isLoading}>
            Delete Manager
          </Button>
        </div>
      </div>
    </div>
  );
}

function ManagerAccessControl({
  manager,
  groups,
  disabled,
  onAssign,
  onRemove,
}: {
  manager: ManagerAccount;
  groups: ManagerGroupAccess[];
  disabled: boolean;
  onAssign: (groupId: string) => void;
  onRemove: (groupId: string) => void;
}) {
  const createdIds = new Set(manager.created_groups.map((group) => group.id));
  const assignedIds = new Set(manager.assigned_groups.map((group) => group.id));
  const assignableGroups = groups.filter((group) => !createdIds.has(group.id) && !assignedIds.has(group.id));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
          <ShieldCheck className="h-3.5 w-3.5" />
          Own groups ({manager.created_groups.length})
        </span>
        {manager.assigned_groups.map((group) => (
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
    </div>
  );
}
