"use client";

import { type FormEvent, useRef, useState } from "react";
import { Plus, Users } from "lucide-react";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { selectUserRole, useAuthStore } from "@/stores/auth.store";
import { useCreateManager, useDeleteManager, useManagers } from "../../hooks/use-operations";
import type { ManagerAccount } from "../../api/operations.api";
import { ManagedAccountControls } from "../managed-account-controls";
import { CreateManagerDialog } from "./create-manager-dialog";
import { DeleteManagerDialog } from "./delete-manager-dialog";
import { ManagerInvitationDialog } from "./manager-invitation-dialog";

export function ManagerAdministrationPage() {
  const { data: managers = [], isLoading, error } = useManagers();
  const role = useAuthStore(selectUserRole);
  const canDeleteManagers = role === "super_admin";
  const createManager = useCreateManager();
  const deleteManager = useDeleteManager();
  const [form, setForm] = useState({ full_name: "", email: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [managerDeleteTarget, setManagerDeleteTarget] = useState<ManagerAccount | null>(null);
  const [deleteOwnedData, setDeleteOwnedData] = useState(false);
  const [issuedInvitation, setIssuedInvitation] = useState<ManagerAccount | null>(null);
  const createManagerButtonRef = useRef<HTMLButtonElement>(null);

  const creating = useRef(false);
  const deleting = useRef(false);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (creating.current || createManager.isPending) return;
    creating.current = true;
    setFormError(null);
    try {
      const manager = await createManager.mutateAsync(form);
      if (!manager.activation_token) throw new Error("Activation token was not returned");
      setIssuedInvitation(manager);
      setForm({ full_name: "", email: "" });
      setShowCreateDialog(false);
    } catch {
      setFormError("Could not create manager. Check whether the email already exists.");
    } finally { creating.current = false; }
  };

  return (
    <div className="flex flex-col gap-6">
      <WorkspacePageHeader
        icon={Users}
        title="Admin"
        description="Create manager accounts for operational access across groups."
        actions={(
          <Button ref={createManagerButtonRef} type="button" onClick={() => setShowCreateDialog(true)}>
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
                          <Badge variant={manager.credential_state === "invited" ? "warning" : manager.is_active ? "success" : "outline"} dot>
                            {manager.credential_state === "invited" ? "Invited" : manager.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center justify-end gap-2">
                            <ManagedAccountControls
                              accountId={manager.id}
                              accountName={manager.full_name}
                              isActive={manager.is_active}
                              allowMfaReset
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
        onClose={() => { if (!deleting.current) setManagerDeleteTarget(null); }}
        onConfirm={() => {
          if (!canDeleteManagers || !managerDeleteTarget || deleting.current || deleteManager.isPending) return;
          deleting.current = true;
          deleteManager.mutate(
            { managerId: managerDeleteTarget.id, deleteOwnedData },
            { onSuccess: () => setManagerDeleteTarget(null), onSettled: () => { deleting.current = false; } },
          );
        }}
      />

      {showCreateDialog && (
        <CreateManagerDialog
          form={form}
          formError={formError}
          isLoading={createManager.isPending}
          onClose={() => {
            if (creating.current) return;
            setShowCreateDialog(false);
            setFormError(null);
          }}
          onFormChange={setForm}
          onSubmit={handleSubmit}
        />
      )}

      {issuedInvitation?.activation_token && (
        <ManagerInvitationDialog
          manager={issuedInvitation}
          onClose={() => {
            setIssuedInvitation(null);
            window.requestAnimationFrame(() => createManagerButtonRef.current?.focus());
          }}
        />
      )}
    </div>
  );
}

