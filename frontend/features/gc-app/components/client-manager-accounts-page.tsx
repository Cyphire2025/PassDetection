"use client";

import { Copy, Search, UserPlus, Users } from "lucide-react";
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
import { GcDialog } from "./gc-dialog";

export function ClientManagerAccountsPage() {
  const { agencyId } = useGcAppAgencyScope();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<GcAppAccountStatus | "all">("all");
  const [page, setPage] = useState(1);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ClientManagerAccount | null>(null);
  const [selected, setSelected] = useState<ClientManagerAccount | null>(null);
  const [activationResult, setActivationResult] = useState<ClientManagerAccount | null>(null);
  const [activationCopied, setActivationCopied] = useState(false);
  const debouncedSearch = useDebounce(search, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, status } as const;
  const managers = useClientManagers(agencyId, filters);
  const mutations = useClientManagerMutations(agencyId);
  const activationValue = activationResult?.activation_token
    ? `groupcompanion://activate?token=${encodeURIComponent(activationResult.activation_token)}`
    : activationResult?.temporary_password ?? null;

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
      const created = await mutations.create.mutateAsync(body);
      if (created.activation_token || created.temporary_password) setActivationResult(created);
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

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
            <Input
              label="Search accounts"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value);
                setPage(1);
              }}
              placeholder="Name, email or mobile number"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
            />
            <div className="flex flex-col gap-1.5">
              <label htmlFor="client-manager-status-filter" className="text-sm font-medium text-slate-700">Account status</label>
              <select
                id="client-manager-status-filter"
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as GcAppAccountStatus | "all");
                  setPage(1);
                }}
                className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
              >
                <option value="all">All statuses</option>
                <option value="invited">Invited</option>
                <option value="active">Active</option>
                <option value="suspended">Suspended</option>
                <option value="deleted">Deleted</option>
              </select>
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
                  <tr key={manager.id} className="hover:bg-slate-50/70">
                    <td className="px-5 py-4">
                      <p className="font-medium text-slate-900">{manager.name}</p>
                      <p className="text-xs text-slate-500">{manager.email} · {manager.phone_number}</p>
                    </td>
                    <td className="px-5 py-4 text-slate-700">{manager.company.name}</td>
                    <td className="px-5 py-4">
                      <span className="font-medium text-slate-800">{manager.assigned_groups.length}</span>
                      <span className="ml-1 text-slate-500">explicit</span>
                    </td>
                    <td className="px-5 py-4 text-slate-600">{manager.last_login_at ? formatGcDateTime(manager.last_login_at) : "Never"}</td>
                    <td className="px-5 py-4"><AccountStatusBadge status={manager.status} /></td>
                    <td className="px-5 py-4 text-right">
                      <Button type="button" variant="secondary" size="sm" onClick={() => setSelected(manager)}>Manage</Button>
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

      <GcDialog
        open={Boolean(activationResult)}
        title="Secure initial activation"
        description={activationResult ? `Copy ${activationResult.name}'s one-time activation details now. They will not be available again.` : undefined}
        onClose={() => {
          setActivationResult(null);
          setActivationCopied(false);
        }}
        size="md"
        footer={(
          <Button type="button" onClick={() => {
            setActivationResult(null);
            setActivationCopied(false);
          }}>I have stored it securely</Button>
        )}
      >
        {activationResult && (
          <div className="space-y-4">
            <GcAlert tone="info" message="Share this secret only through an approved secure channel. Do not place it in audit notes or ordinary chat messages." />
            <div className="rounded-xl border border-slate-200 bg-slate-950 p-4 text-slate-50">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{activationResult.activation_token ? "Single-use app activation link" : "Temporary password"}</p>
              <code className="mt-2 block break-all text-sm">{activationValue}</code>
            </div>
            <Button
              type="button"
              variant="secondary"
              leftIcon={<Copy className="h-4 w-4" aria-hidden="true" />}
              onClick={() => {
                if (!activationValue) return;
                void navigator.clipboard.writeText(activationValue).then(() => setActivationCopied(true));
              }}
            >
              {activationCopied ? "Copied" : activationResult.activation_token ? "Copy activation link once" : "Copy password once"}
            </Button>
          </div>
        )}
      </GcDialog>
    </div>
  );
}
