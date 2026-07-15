"use client";

import { FormEvent, useState } from "react";
import { Plus, UserPlus, Users, X } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Badge, Button, Card, CardContent, Input, PasswordInput, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import {
  useCreateManager,
  useDeleteManager,
  useManagers,
} from "@/features/operations/hooks/use-operations";
import type { ManagerAccount } from "@/features/operations/api/operations.api";
import { ManagedAccountControls } from "@/features/operations/components/managed-account-controls";

export default function AdminPage() {
  const { data: managers = [], isLoading, error } = useManagers();
  const role = useAuthStore(selectUserRole);
  const canDeleteManagers = role === "super_admin";
  const createManager = useCreateManager();
  const deleteManager = useDeleteManager();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [managerDeleteTarget, setManagerDeleteTarget] = useState<ManagerAccount | null>(null);
  const [deleteOwnedData, setDeleteOwnedData] = useState(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);
    if (form.password.length < 10 || !/[A-Z]/.test(form.password) || !/[a-z]/.test(form.password) || !/\d/.test(form.password)) {
      setFormError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }

    try {
      await createManager.mutateAsync(form);
      setForm({ full_name: "", email: "", password: "" });
      setShowCreateDialog(false);
    } catch {
      setFormError("Could not create manager. Check whether the email already exists.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Admin"
        description="Create manager accounts for operational access across groups."
        actions={(
          <Button type="button" onClick={() => setShowCreateDialog(true)}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            Create Manager
          </Button>
        )}
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Manager administration is unavailable for this account.
        </div>
      )}

      <div className="grid gap-6">
        <Card className="min-w-0">
          <CardContent className="p-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-6 py-5">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                  <Users className="h-5 w-5" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-slate-900">Managers</h2>
                  <p className="mt-0.5 text-sm text-slate-500">Managers can access operational modules across all agency groups.</p>
                </div>
              </div>
              <Badge variant="secondary" className="px-3 py-1">{managers.length} total</Badge>
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
              <div className="overflow-x-auto overflow-y-visible">
                <table className="w-full min-w-[980px] table-fixed text-left text-sm">
                  <colgroup>
                    <col className="w-[36%]" />
                    <col className="w-[20%]" />
                    <col className="w-[20%]" />
                    <col className="w-[12%]" />
                    <col className="w-[12%]" />
                  </colgroup>
                  <thead className="border-b border-slate-200 bg-slate-50/80 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-6 py-3.5">Manager</th>
                      <th className="px-5 py-3.5">Created</th>
                      <th className="px-5 py-3.5">Last login</th>
                      <th className="px-5 py-3.5">Status</th>
                      <th className="px-6 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {managers.map((manager) => (
                      <tr key={manager.id} className="hover:bg-slate-50/70">
                        <td className="px-6 py-4">
                          <div className="font-semibold text-slate-900">{manager.full_name}</div>
                          <div className="mt-1 truncate text-xs text-slate-500">{manager.email}</div>
                        </td>
                        <td className="whitespace-nowrap px-5 py-4 text-slate-600">{formatDateTime(manager.created_at)}</td>
                        <td className="whitespace-nowrap px-5 py-4 text-slate-600">
                          {manager.last_login_at ? formatDateTime(manager.last_login_at) : "Never"}
                        </td>
                        <td className="px-5 py-4">
                          <Badge variant={manager.is_active ? "success" : "outline"} dot>
                            {manager.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center justify-end gap-2">
                            <ManagedAccountControls
                              accountId={manager.id}
                              accountName={manager.full_name}
                              isActive={manager.is_active}
                              deleteLabel="Delete manager"
                              deleteDisabled={!canDeleteManagers || deleteManager.isPending}
                              onDelete={canDeleteManagers ? () => {
                                setDeleteOwnedData(false);
                                setManagerDeleteTarget(manager);
                              } : undefined}
                            />
                          </div>
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

      {showCreateDialog && (
        <CreateManagerDialog
          form={form}
          formError={formError}
          isLoading={createManager.isPending}
          onClose={() => {
            setShowCreateDialog(false);
            setFormError(null);
          }}
          onFormChange={setForm}
          onSubmit={handleSubmit}
        />
      )}
    </div>
  );
}

function CreateManagerDialog({
  form,
  formError,
  isLoading,
  onClose,
  onFormChange,
  onSubmit,
}: {
  form: { full_name: string; email: string; password: string };
  formError: string | null;
  isLoading: boolean;
  onClose: () => void;
  onFormChange: React.Dispatch<React.SetStateAction<{ full_name: string; email: string; password: string }>>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card className="w-full max-w-lg overflow-hidden shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100">
                <UserPlus className="h-5 w-5" />
              </span>
              <div className="min-w-0">
                <h2 className="text-base font-semibold text-slate-900">Create Manager</h2>
                <p className="mt-0.5 text-sm leading-5 text-slate-500">Managers can create groups and work on assigned groups.</p>
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
              placeholder="Example: Rahul Mehta"
              value={form.full_name}
              onChange={(event) => onFormChange((current) => ({ ...current, full_name: event.target.value }))}
              required
            />
            <Input
              label="Email"
              type="email"
              placeholder="manager@company.com"
              value={form.email}
              onChange={(event) => onFormChange((current) => ({ ...current, email: event.target.value }))}
              required
            />
            <PasswordInput
              label="Temporary password"
              placeholder="Minimum 10 characters"
              value={form.password}
              onChange={(event) => onFormChange((current) => ({ ...current, password: event.target.value }))}
              required
            />
            <p className="text-xs leading-5 text-slate-500">
              Password must include uppercase, lowercase, and a number. It can be reset later by an admin.
            </p>
            {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
            <div className="flex justify-end gap-3 pt-1">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>
                Create Manager
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
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
