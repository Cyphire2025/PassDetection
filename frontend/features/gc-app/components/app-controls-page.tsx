"use client";

import Link from "next/link";
import { AlertTriangle, Plus, Search, Settings2, Smartphone } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input, buttonVariants } from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { cn } from "@/lib/utils/cn";
import { GC_APP_DEFAULT_PAGE_SIZE } from "../api/gc-app-admin.api";
import { useClientCompanies, useClientCompanyMutations, useGcAppGroupMutations, useGcAppGroups, useGcGroupSearch } from "../hooks/use-gc-app-admin";
import type { GcAppGroupControl, GcAppGroupLifecycle } from "../types";
import { formatGcDateTime, gcAppErrorMessage } from "../utils";
import { AccessSwitch, GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcDialog } from "./gc-dialog";

type PendingGroupAction = { type: "revoke" | "remove"; group: GcAppGroupControl } | null;

export function AppControlsPage() {
  const { agencyId } = useGcAppAgencyScope();
  const [search, setSearch] = useState("");
  const [lifecycle, setLifecycle] = useState<GcAppGroupLifecycle | "all">("all");
  const [page, setPage] = useState(1);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerCompanyId, setPickerCompanyId] = useState("");
  const [newCompanyName, setNewCompanyName] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingGroupAction>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const debouncedSearch = useDebounce(search, 300);
  const debouncedPickerSearch = useDebounce(pickerSearch, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, lifecycle } as const;
  const groups = useGcAppGroups(agencyId, filters);
  const candidates = useGcGroupSearch(
    agencyId,
    { page: 1, page_size: 20, search: debouncedPickerSearch },
    true,
    pickerOpen,
  );
  const companies = useClientCompanies(agencyId);
  const companyActions = useClientCompanyMutations(agencyId);
  const actions = useGcAppGroupMutations(agencyId);
  const mutationPending = actions.add.isPending
    || actions.updateControl.isPending
    || actions.revoke.isPending
    || actions.remove.isPending;

  const updateAccess = async (
    group: GcAppGroupControl,
    field: "passenger_access_enabled" | "client_manager_access_enabled" | "coordinator_access_enabled",
    enabled: boolean,
  ) => {
    setActionError(null);
    try {
      await actions.updateControl.mutateAsync({
        control: group,
        patch: { [field]: enabled },
      });
    } catch (error) {
      setActionError(gcAppErrorMessage(error, "Access was not changed. Refresh and try again."));
    }
  };

  const confirmGroupAction = async () => {
    if (!pendingAction) return;
    setActionError(null);
    try {
      if (pendingAction.type === "revoke") {
        await actions.revoke.mutateAsync(pendingAction.group.id);
      } else {
        await actions.remove.mutateAsync(pendingAction.group);
      }
      setPendingAction(null);
    } catch (error) {
      setActionError(gcAppErrorMessage(error, "The group access action could not be completed."));
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="App Controls"
        description="Explicitly enable groups, configure role access, publish content, and revoke mobile access."
        actions={(
          <Button type="button" leftIcon={<Plus className="h-4 w-4" />} onClick={() => setPickerOpen(true)}>
            Add group to GC App
          </Button>
        )}
      />

      {actionError && <GcAlert message={actionError} />}

      <Card>
        <CardContent className="grid gap-3 p-5 md:grid-cols-[minmax(0,1fr)_220px]">
          <Input
            label="Search enabled groups"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Group name or destination"
            leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="gc-group-company" className="text-sm font-medium text-slate-700">Assigned company/client</label>
            <select
              id="gc-group-company"
              value={pickerCompanyId}
              onChange={(event) => setPickerCompanyId(event.target.value)}
              className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">Select company/client before adding</option>
              {companies.data?.items.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
            </select>
            {companies.isError && <p role="alert" className="text-xs text-red-700">Companies could not be loaded.</p>}
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="gc-group-lifecycle" className="text-sm font-medium text-slate-700">Group lifecycle</label>
            <select
              id="gc-group-lifecycle"
              value={lifecycle}
              onChange={(event) => {
                setLifecycle(event.target.value as GcAppGroupLifecycle | "all");
                setPage(1);
              }}
              className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="all">All lifecycle states</option>
              <option value="active">Active</option>
              <option value="closed">Closed</option>
              <option value="archived">Archived</option>
              <option value="deleted">Deleted</option>
            </select>
          </div>
        </CardContent>
      </Card>

      {groups.isLoading ? (
        <Card><GcLoadingRows count={3} /></Card>
      ) : groups.isError ? (
        <Card><CardContent className="space-y-3 p-5"><GcAlert message="GC App groups could not be loaded." /><Button type="button" variant="secondary" size="sm" onClick={() => void groups.refetch()}>Retry</Button></CardContent></Card>
      ) : groups.data?.items.length === 0 ? (
        <EmptyState
          icon={<Smartphone className="h-5 w-5" aria-hidden="true" />}
          title="No groups enabled in GC App"
          description={search || lifecycle !== "all" ? "Adjust the search or lifecycle filter." : "Groups remain unavailable in the mobile app until staff explicitly add them here."}
          action={!search && lifecycle === "all" ? { label: "Add group to GC App", onClick: () => setPickerOpen(true) } : undefined}
        />
      ) : (
        <div className="space-y-4">
          {groups.data?.items.map((group) => (
            <GroupControlCard
              key={group.id}
              group={group}
              disabled={mutationPending}
              onAccessChange={(field, enabled) => void updateAccess(group, field, enabled)}
              onRevoke={() => setPendingAction({ type: "revoke", group })}
              onRemove={() => setPendingAction({ type: "remove", group })}
            />
          ))}
          {groups.data && (
            <Card>
              <GcPagination
                page={groups.data.page}
                total={groups.data.total}
                pageSize={groups.data.page_size}
                hasNext={groups.data.has_next}
                disabled={groups.isFetching}
                onPageChange={setPage}
              />
            </Card>
          )}
        </div>
      )}

      <GcDialog
        open={pickerOpen}
        title="Add group to GC App"
        description="Only active eligible groups appear here. Adding a group does not enable any user role automatically."
        onClose={() => !actions.add.isPending && setPickerOpen(false)}
        closeDisabled={actions.add.isPending}
        size="lg"
      >
        <div className="space-y-4">
          <div className="space-y-2 rounded-xl border border-slate-200 p-4">
            <label htmlFor="gc-app-group-company" className="block text-sm font-medium text-slate-700">
              Assigned company/client
            </label>
            <select
              id="gc-app-group-company"
              value={pickerCompanyId}
              onChange={(event) => setPickerCompanyId(event.target.value)}
              className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">Select company/client</option>
              {companies.data?.items.map((company) => (
                <option key={company.id} value={company.id}>{company.name}</option>
              ))}
            </select>
            <div className="flex gap-2">
              <Input
                aria-label="New company or client name"
                value={newCompanyName}
                onChange={(event) => setNewCompanyName(event.target.value)}
                placeholder="Create a company/client"
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={!newCompanyName.trim()}
                isLoading={companyActions.create.isPending}
                onClick={() => {
                  const name = newCompanyName.trim();
                  if (!name) return;
                  setActionError(null);
                  void companyActions.create.mutateAsync(name).then((company) => {
                    setPickerCompanyId(company.id);
                    setNewCompanyName("");
                  }).catch((error: unknown) => {
                    setActionError(gcAppErrorMessage(error, "The company/client could not be created."));
                  });
                }}
              >
                Add
              </Button>
            </div>
          </div>
          <Input
            label="Search dashboard groups"
            value={pickerSearch}
            onChange={(event) => setPickerSearch(event.target.value)}
            placeholder="Group name or destination"
            leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
          />
          <div className="max-h-[50dvh] overflow-y-auto rounded-xl border border-slate-200">
            {candidates.isLoading ? <GcLoadingRows count={3} /> : candidates.isError ? (
              <p role="alert" className="p-4 text-sm text-red-700">Eligible groups could not be searched.</p>
            ) : candidates.data?.items.length === 0 ? (
              <p className="p-6 text-center text-sm text-slate-500">No eligible active groups found.</p>
            ) : candidates.data?.items.map((group) => (
              <div key={group.id} className="flex items-center justify-between gap-4 border-b border-slate-100 p-4 last:border-0">
                <div>
                  <p className="font-medium text-slate-900">{group.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{group.destination ?? "Destination not set"} · {group.company?.name ?? "Client not assigned"}</p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  isLoading={actions.add.isPending && actions.add.variables?.group.id === group.id}
                  disabled={actions.add.isPending || !pickerCompanyId}
                  onClick={() => {
                    setActionError(null);
                    const company = companies.data?.items.find((item) => item.id === pickerCompanyId);
                    if (!company) {
                      setActionError("Select the company/client that owns this group.");
                      return;
                    }
                    void actions.add.mutateAsync({ group, company }).then(() => {
                      setPickerOpen(false);
                      setPickerCompanyId("");
                    }).catch((error: unknown) => {
                      setActionError(gcAppErrorMessage(error, "The group could not be added to GC App."));
                    });
                  }}
                >
                  Add
                </Button>
              </div>
            ))}
          </div>
        </div>
      </GcDialog>

      <GcDialog
        open={Boolean(pendingAction)}
        title={pendingAction?.type === "remove" ? "Remove group from GC App" : "Immediately revoke mobile access"}
        description={pendingAction ? `${pendingAction.group.name} · This action is enforced by the GC App backend and does not close, archive, delete, or revoke the existing passport collection group.` : undefined}
        onClose={() => !mutationPending && setPendingAction(null)}
        closeDisabled={mutationPending}
        size="md"
        footer={(
          <>
            <Button type="button" variant="secondary" onClick={() => setPendingAction(null)} disabled={mutationPending}>Cancel</Button>
            <Button type="button" variant="danger" isLoading={mutationPending} onClick={() => void confirmGroupAction()}>
              {pendingAction?.type === "remove" ? "Remove from GC App" : "Revoke access now"}
            </Button>
          </>
        )}
      >
        <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <p>{pendingAction?.type === "remove" ? "All mobile roles will lose access and the group will leave this control list. Published travel data remains in the platform audit history." : "All currently signed-in mobile users for this group will be denied on their next backend request and devices will be instructed to clear scoped offline data."}</p>
        </div>
      </GcDialog>
    </div>
  );
}

function GroupControlCard({
  group,
  disabled,
  onAccessChange,
  onRevoke,
  onRemove,
}: {
  group: GcAppGroupControl;
  disabled: boolean;
  onAccessChange: (
    field: "passenger_access_enabled" | "client_manager_access_enabled" | "coordinator_access_enabled",
    enabled: boolean,
  ) => void;
  onRevoke: () => void;
  onRemove: () => void;
}) {
  const lifecycleBlocked = group.lifecycle === "archived" || group.lifecycle === "deleted";
  return (
    <Card className={group.access_revoked_at ? "border-red-200" : undefined}>
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold text-slate-900">{group.name}</h3>
              <Badge variant={lifecycleVariant(group.lifecycle)}>{capitalize(group.lifecycle)}</Badge>
              {group.access_revoked_at && <Badge variant="destructive">Access revoked</Badge>}
            </div>
            <p className="mt-1 text-sm text-slate-500">{group.destination ?? "Destination not set"} · {group.company?.name ?? "Client not assigned"}</p>
            <p className="mt-1 text-xs text-slate-500">
              Access window: {group.access_starts_at ? formatGcDateTime(group.access_starts_at) : "Immediate"} – {group.access_expires_at ? formatGcDateTime(group.access_expires_at) : "No expiry"}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href={ROUTES.dashboard.gcAppGroup(group.id) as never}
              className={cn(buttonVariants({ variant: "secondary", size: "sm" }))}
            >
              <Settings2 className="h-4 w-4" aria-hidden="true" />
              Manage & publish
            </Link>
            <Button type="button" variant="secondary" size="sm" onClick={onRevoke} disabled={disabled || Boolean(group.access_revoked_at)}>
              Revoke now
            </Button>
            <Button type="button" variant="ghost" size="sm" className="text-red-700 hover:bg-red-50 hover:text-red-800" onClick={onRemove} disabled={disabled}>
              Remove
            </Button>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <AccessSwitch label="Passenger access" checked={group.passenger_access_enabled} disabled={disabled || lifecycleBlocked || Boolean(group.access_revoked_at)} onChange={(enabled) => onAccessChange("passenger_access_enabled", enabled)} />
          <AccessSwitch label="Client Manager access" checked={group.client_manager_access_enabled} disabled={disabled || lifecycleBlocked || Boolean(group.access_revoked_at)} onChange={(enabled) => onAccessChange("client_manager_access_enabled", enabled)} />
          <AccessSwitch label="Coordinator access" checked={group.coordinator_access_enabled} disabled={disabled || lifecycleBlocked || Boolean(group.access_revoked_at)} onChange={(enabled) => onAccessChange("coordinator_access_enabled", enabled)} />
        </div>

        <dl className="grid gap-3 border-t border-slate-100 pt-4 text-sm sm:grid-cols-2 lg:grid-cols-6">
          <Metric label="Active mobile users" value={group.active_mobile_users} />
          <Metric label="Synced devices" value={group.synced_device_count} />
          <Metric label="Last successful sync" value={group.last_successful_sync_at ? formatGcDateTime(group.last_successful_sync_at) : "Never"} />
          <Metric label="Itinerary version" value={`v${group.versions.itinerary_version}`} />
          <Metric label="Document version" value={`v${group.versions.common_document_version}`} />
          <Metric label="Announcement version" value={`v${group.versions.announcement_version}`} />
        </dl>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return <div><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-medium text-slate-800">{value}</dd></div>;
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function lifecycleVariant(lifecycle: GcAppGroupLifecycle): "success" | "warning" | "outline" | "destructive" {
  if (lifecycle === "active") return "success";
  if (lifecycle === "closed") return "warning";
  if (lifecycle === "deleted") return "destructive";
  return "outline";
}
