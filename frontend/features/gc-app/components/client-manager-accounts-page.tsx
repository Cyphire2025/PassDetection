"use client";

import { ChevronRight, Search, ShieldCheck, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input } from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { useDebounce } from "@/hooks/use-debounce";
import { GC_APP_DEFAULT_PAGE_SIZE } from "../api/gc-app-admin.api";
import { useClientManagerMutations, useClientManagers } from "../hooks/use-gc-app-admin";
import type { ClientManagerAccount, ClientManagerInput, GcAppAccountStatus } from "../types";
import { formatGcDateTime } from "../utils";
import { AccountStatusBadge, ClientManagerDetailsDialog } from "./client-manager-details-dialog";
import { ClientManagerFormDialog } from "./client-manager-form-dialog";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { GcSelect } from "./gc-select";

const STATUS_OPTIONS = [
  { value: "all", label: "All account statuses" },
  { value: "invited", label: "Invited", description: "Activation is still pending" },
  { value: "active", label: "Active", description: "Can sign in to the companion app" },
  { value: "suspended", label: "Suspended", description: "Access is temporarily blocked" },
  { value: "deleted", label: "Deleted", description: "Retained only for audit history" },
] as const;

export function ClientManagerAccountsPage() {
  const { agencyId } = useGcAppAgencyScope();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<GcAppAccountStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ClientManagerAccount | null>(null);
  const [selected, setSelected] = useState<ClientManagerAccount | null>(null);
  const debouncedSearch = useDebounce(search, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, status } as const;
  const managers = useClientManagers(agencyId, filters);
  const mutations = useClientManagerMutations(agencyId);
  const saveManager = async (body: ClientManagerInput) => {
    if (editing) {
      const update = {
        name: body.name,
        email: body.email,
        phone_number: body.phone_number,
        company_id: body.company_id,
        group_ids: body.group_ids,
        force_password_change: body.force_password_change,
      };
      await mutations.update.mutateAsync({ managerId: editing.id, current: editing, body: update });
    } else {
      await mutations.create.mutateAsync(body);
    }
    setFormOpen(false);
    setEditing(null);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Client Manager Accounts"
        description="Create and manage client-side accounts with explicit company and group assignments."
        actions={(
          <Button
            type="button"
            leftIcon={<UserPlus className="h-4 w-4" aria-hidden="true" />}
            onClick={() => {
              setEditing(null);
              setFormOpen(true);
            }}
          >
            Create account
          </Button>
        )}
      />

      <Card className="overflow-visible border-slate-200/80 shadow-[0_8px_30px_-24px_rgba(15,23,42,0.45)]">
        <CardContent className="p-4 sm:p-5">
          <div className="grid gap-3 lg:grid-cols-[minmax(18rem,1fr)_18rem_auto] lg:items-end">
            <Input
              label="Find a Client Manager"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Name, email or mobile number"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
            />
            <GcSelect
              id="client-manager-status-filter"
              label="Account status"
              value={status}
              options={STATUS_OPTIONS}
              onChange={(nextStatus) => {
                setStatus(nextStatus as GcAppAccountStatus | "all");
                setPage(1);
              }}
            />
            <div className="hidden h-10 items-center gap-2 rounded-xl bg-slate-50 px-3 text-xs font-medium text-slate-600 lg:flex">
              <ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden="true" />
              Explicit access only
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h3 className="font-semibold text-slate-900">Accounts</h3>
            <p className="mt-0.5 text-xs text-slate-500">Personal-document access is disabled by default and is not configurable here.</p>
          </div>
          <Badge variant="secondary">{managers.data?.total ?? 0} total</Badge>
        </div>

        {managers.isLoading ? (
          <GcLoadingRows />
        ) : managers.isError ? (
          <div className="space-y-3 p-5">
            <GcAlert message="Client Manager accounts could not be loaded. No account state was changed." />
            <Button type="button" variant="secondary" size="sm" onClick={() => void managers.refetch()}>Retry</Button>
          </div>
        ) : managers.data?.items.length === 0 ? (
          <div className="p-5">
            <EmptyState
              icon={<Users className="h-5 w-5" aria-hidden="true" />}
              title="No Client Manager accounts found"
              description={search || status !== "all" ? "Adjust the search or status filter." : "Create the first account when the company and group assignments are ready."}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[960px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-5 py-3">Client Manager</th>
                  <th className="px-5 py-3">Company/client</th>
                  <th className="px-5 py-3">Assigned groups</th>
                  <th className="px-5 py-3">Last login</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {managers.data?.items.map((manager) => (
                  <tr key={manager.id} className="group transition-colors hover:bg-blue-50/35">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white shadow-sm" aria-hidden="true">
                          {manager.name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase()}
                        </span>
                        <span className="min-w-0">
                          <span className="block font-semibold text-slate-900">{manager.name}</span>
                          <span className="block text-xs text-slate-500">{manager.email} · {manager.phone_number}</span>
                        </span>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-slate-700">{manager.company.name}</td>
                    <td className="px-5 py-4">
                      <span className="font-medium text-slate-800">{manager.assigned_groups.length}</span>
                      <span className="ml-1 text-slate-500">explicit</span>
                    </td>
                    <td className="px-5 py-4 text-slate-600">{manager.last_login_at ? formatGcDateTime(manager.last_login_at) : "Never"}</td>
                    <td className="px-5 py-4"><AccountStatusBadge status={manager.status} /></td>
                    <td className="px-5 py-4 text-right">
                      {manager.status === "deleted" ? (
                        <span className="text-xs font-medium text-slate-500">Audit record</span>
                      ) : (
                        <Button type="button" variant="ghost" size="sm" className="text-blue-700 hover:bg-blue-50 hover:text-blue-800" rightIcon={<ChevronRight className="h-4 w-4" aria-hidden="true" />} onClick={() => setSelected(manager)}>Open profile</Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {managers.data && (
          <GcPagination
            page={managers.data.page}
            total={managers.data.total}
            pageSize={managers.data.page_size}
            hasNext={managers.data.has_next}
            disabled={managers.isFetching}
            onPageChange={setPage}
          />
        )}
      </Card>

      {formOpen && (
        <ClientManagerFormDialog
          open
          agencyId={agencyId}
          manager={editing}
          isPending={mutations.create.isPending || mutations.update.isPending}
          onClose={() => {
            if (mutations.create.isPending || mutations.update.isPending) return;
            setFormOpen(false);
            setEditing(null);
          }}
          onSubmit={saveManager}
        />
      )}

      <ClientManagerDetailsDialog
        open={Boolean(selected)}
        agencyId={agencyId}
        manager={selected}
        onClose={() => setSelected(null)}
        onEdit={() => {
          if (!selected) return;
          setEditing(selected);
          setSelected(null);
          setFormOpen(true);
        }}
      />
    </div>
  );
}
