"use client";

import Link from "next/link";
import { AlertTriangle, Building2, Plus, Search, Settings2, Smartphone, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent, Input, buttonVariants } from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useDebounce } from "@/hooks/use-debounce";
import { cn } from "@/lib/utils/cn";
import { GC_APP_DEFAULT_PAGE_SIZE } from "../api/gc-app-admin.api";
import { useClientCompanies, useClientCompanyMutations, useGcAppGroupMutations, useGcAppGroups, useGcGroupSearch } from "../hooks/use-gc-app-admin";
import type { GcAppGroupControl, GcAppGroupLifecycle, GcCompanyReference } from "../types";
import { formatGcDateTime, gcAppErrorMessage } from "../utils";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
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
  const [pickerPage, setPickerPage] = useState(1);
  const [companySearch, setCompanySearch] = useState("");
  const [companyPage, setCompanyPage] = useState(1);
  const [pickerCompanyId, setPickerCompanyId] = useState("");
  const [pickerCompany, setPickerCompany] = useState<GcCompanyReference | null>(null);
  const [newCompanyName, setNewCompanyName] = useState("");
  const [pickerError, setPickerError] = useState<string | null>(null);
  const [pendingCompanyRemoval, setPendingCompanyRemoval] = useState<GcCompanyReference | null>(null);
  const [companyRemovalConfirmation, setCompanyRemovalConfirmation] = useState("");
  const [pendingAction, setPendingAction] = useState<PendingGroupAction>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const debouncedSearch = useDebounce(search, 300);
  const debouncedPickerSearch = useDebounce(pickerSearch, 300);
  const debouncedCompanySearch = useDebounce(companySearch, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, lifecycle } as const;
  const groups = useGcAppGroups(agencyId, filters);
  const candidates = useGcGroupSearch(
    agencyId,
    { page: pickerPage, page_size: 20, search: debouncedPickerSearch },
    true,
    pickerOpen,
  );
  const companies = useClientCompanies(agencyId, debouncedCompanySearch, companyPage, 20);
  const companyActions = useClientCompanyMutations(agencyId);
  const actions = useGcAppGroupMutations(agencyId);
  const companyItems = companies.data?.items ?? [];
  const activeCompanies = companyItems.filter((company) => company.status !== "inactive");
  const selectableCompanies = pickerCompany && !activeCompanies.some((company) => company.id === pickerCompany.id)
    ? [pickerCompany, ...activeCompanies]
    : activeCompanies;
  const pickerBusy = actions.add.isPending || companyActions.create.isPending || companyActions.remove.isPending;
  const mutationPending = actions.add.isPending
    || actions.revoke.isPending
    || actions.remove.isPending;

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

  const openPicker = () => {
    setPickerError(null);
    setPendingCompanyRemoval(null);
    setCompanyRemovalConfirmation("");
    setPickerPage(1);
    setPickerOpen(true);
  };

  const closePicker = () => {
    if (pickerBusy) return;
    setPickerOpen(false);
    setPickerError(null);
    setPendingCompanyRemoval(null);
    setCompanyRemovalConfirmation("");
  };

  const removeCompany = async () => {
    if (!pendingCompanyRemoval || companyRemovalConfirmation.trim() !== pendingCompanyRemoval.name) return;
    setPickerError(null);
    try {
      await companyActions.remove.mutateAsync(pendingCompanyRemoval);
      if (pickerCompanyId === pendingCompanyRemoval.id) {
        setPickerCompanyId("");
        setPickerCompany(null);
      }
      setPendingCompanyRemoval(null);
      setCompanyRemovalConfirmation("");
    } catch (error) {
      setPickerError(gcAppErrorMessage(error, "The company/client could not be removed."));
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="App Controls"
        description="Explicitly enable groups, configure role access, publish content, and revoke mobile access."
        actions={(
          <Button type="button" leftIcon={<Plus className="h-4 w-4" />} onClick={openPicker}>
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
              onChange={(event) => {
                const id = event.target.value;
                setPickerCompanyId(id);
                setPickerCompany(selectableCompanies.find((company) => company.id === id) ?? null);
              }}
              className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">Select company/client before adding</option>
              {selectableCompanies.map((company) => <option key={company.id} value={company.id}>{company.name}</option>)}
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
          action={!search && lifecycle === "all" ? { label: "Add group to GC App", onClick: openPicker } : undefined}
        />
      ) : (
        <div className="space-y-4">
          {groups.data?.items.map((group) => (
            <GroupControlCard
              key={group.id}
              group={group}
              disabled={mutationPending}
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
        description="Only active eligible groups appear here. Passenger, Client Manager, and Coordinator access are enabled by default and can be changed in Manage & publish."
        onClose={closePicker}
        closeDisabled={pickerBusy}
        size="lg"
      >
        <div className="space-y-4">
          {pickerError && <GcAlert message={pickerError} />}
          <div className="space-y-4 rounded-xl border border-slate-200 p-4">
            <label htmlFor="gc-app-group-company" className="block text-sm font-medium text-slate-700">
              Assigned company/client
            </label>
            <Input
              aria-label="Search saved company or client"
              value={companySearch}
              onChange={(event) => {
                setCompanySearch(event.target.value);
                setCompanyPage(1);
              }}
              placeholder="Search company/client"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
            />
            <select
              id="gc-app-group-company"
              value={pickerCompanyId}
              onChange={(event) => {
                const id = event.target.value;
                setPickerCompanyId(id);
                setPickerCompany(selectableCompanies.find((company) => company.id === id) ?? null);
              }}
              className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600"
            >
              <option value="">Select company/client</option>
              {selectableCompanies.map((company) => (
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
                  setPickerError(null);
                  void companyActions.create.mutateAsync(name).then((company) => {
                    setPickerCompanyId(company.id);
                    setPickerCompany(company);
                    setNewCompanyName("");
                  }).catch((error: unknown) => {
                    setPickerError(gcAppErrorMessage(error, "The company/client could not be created."));
                  });
                }}
              >
                Add
              </Button>
            </div>

            <div className="border-t border-slate-200 pt-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Building2 className="h-4 w-4 text-slate-500" aria-hidden="true" />
                    Saved company/clients
                  </h3>
                  <p className="mt-1 text-xs text-slate-500">Search and page through company/client records in this agency workspace.</p>
                </div>
                <Badge variant="outline">{companies.data?.total ?? 0}</Badge>
              </div>
              <div className="mt-3 max-h-44 overflow-y-auto rounded-lg border border-slate-200">
                {companies.isLoading ? <GcLoadingRows count={2} /> : companies.isError ? (
                  <p role="alert" className="p-4 text-sm text-red-700">Companies could not be loaded.</p>
                ) : activeCompanies.length === 0 ? (
                  <p className="p-4 text-center text-sm text-slate-500">No company/client records have been added.</p>
                ) : activeCompanies.map((company) => (
                  <div key={company.id} className="flex items-center justify-between gap-3 border-b border-slate-100 px-3 py-2.5 last:border-0">
                    <span className="min-w-0 truncate text-sm font-medium text-slate-800">{company.name}</span>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="shrink-0 text-red-700 hover:bg-red-50 hover:text-red-800"
                      leftIcon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
                      disabled={pickerBusy}
                      onClick={() => {
                        setPickerError(null);
                        setPendingCompanyRemoval(company);
                        setCompanyRemovalConfirmation("");
                      }}
                    >
                      Remove
                    </Button>
                  </div>
                ))}
              </div>
              {companies.data && companies.data.total > companies.data.page_size && (
                <GcPagination
                  page={companies.data.page}
                  total={companies.data.total}
                  pageSize={companies.data.page_size}
                  hasNext={companies.data.has_next}
                  disabled={companies.isFetching}
                  onPageChange={setCompanyPage}
                />
              )}

              {pendingCompanyRemoval && (
                <div className="mt-3 space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3" role="group" aria-labelledby="remove-company-heading">
                  <div className="flex gap-2 text-sm text-amber-950">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                    <div>
                      <p id="remove-company-heading" className="font-semibold">Remove {pendingCompanyRemoval.name}?</p>
                      <p className="mt-1 text-xs leading-5">Removal is blocked if any enabled GC App group or Client Manager account still uses this company/client. Type the exact name to confirm.</p>
                    </div>
                  </div>
                  <Input
                    aria-label={`Type ${pendingCompanyRemoval.name} to confirm removal`}
                    value={companyRemovalConfirmation}
                    onChange={(event) => setCompanyRemovalConfirmation(event.target.value)}
                    placeholder={pendingCompanyRemoval.name}
                    autoComplete="off"
                  />
                  <div className="flex justify-end gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      disabled={companyActions.remove.isPending}
                      onClick={() => {
                        setPendingCompanyRemoval(null);
                        setCompanyRemovalConfirmation("");
                      }}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      isLoading={companyActions.remove.isPending}
                      disabled={companyRemovalConfirmation.trim() !== pendingCompanyRemoval.name}
                      onClick={() => void removeCompany()}
                    >
                      Remove company/client
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </div>
          <Input
            label="Search dashboard groups"
            value={pickerSearch}
            onChange={(event) => {
              setPickerSearch(event.target.value);
              setPickerPage(1);
            }}
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
                    setPickerError(null);
                    const company = pickerCompany?.id === pickerCompanyId
                      ? pickerCompany
                      : activeCompanies.find((item) => item.id === pickerCompanyId);
                    if (!company) {
                      setPickerError("Select the company/client that owns this group.");
                      return;
                    }
                    void actions.add.mutateAsync({ group, company }).then(() => {
                      setPickerOpen(false);
                      setPickerCompanyId("");
                      setPickerCompany(null);
                      setPendingCompanyRemoval(null);
                      setCompanyRemovalConfirmation("");
                    }).catch((error: unknown) => {
                      setPickerError(gcAppErrorMessage(error, "The group could not be added to GC App."));
                    });
                  }}
                >
                  Add
                </Button>
              </div>
            ))}
          </div>
          {candidates.data && candidates.data.total > candidates.data.page_size && (
            <GcPagination
              page={candidates.data.page}
              total={candidates.data.total}
              pageSize={candidates.data.page_size}
              hasNext={candidates.data.has_next}
              disabled={candidates.isFetching}
              onPageChange={setPickerPage}
            />
          )}
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
  onRevoke,
  onRemove,
}: {
  group: GcAppGroupControl;
  disabled: boolean;
  onRevoke: () => void;
  onRemove: () => void;
}) {
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
