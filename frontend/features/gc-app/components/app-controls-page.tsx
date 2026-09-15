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
import { APP_AVAILABILITY_OPTIONS, describeAppAvailability } from "../availability";
import { useClientCompanies, useClientCompanyMutations, useGcAppGroupMutations, useGcAppGroups, useGcGroupSearch } from "../hooks/use-gc-app-admin";
import type { GcAppAvailability, GcAppGroupControl, GcCompanyReference } from "../types";
import { formatGcDateTime, gcAppErrorMessage } from "../utils";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

export function AppControlsPage() {
  const { agencyId } = useGcAppAgencyScope();
  const [search, setSearch] = useState("");
  const [availability, setAvailability] = useState<GcAppAvailability | "all">("all");
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
  const debouncedSearch = useDebounce(search, 300);
  const debouncedPickerSearch = useDebounce(pickerSearch, 300);
  const debouncedCompanySearch = useDebounce(companySearch, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, availability } as const;
  const groups = useGcAppGroups(agencyId, filters);
  const candidates = useGcGroupSearch(
    agencyId,
    { page: pickerPage, page_size: 20, search: debouncedPickerSearch },
    true,
    pickerOpen,
  );
  const companies = useClientCompanies(agencyId, debouncedCompanySearch, companyPage, 20, pickerOpen);
  const companyActions = useClientCompanyMutations(agencyId);
  const actions = useGcAppGroupMutations(agencyId);
  const companyItems = companies.data?.items ?? [];
  const activeCompanies = companyItems.filter((company) => company.status !== "inactive");
  const selectableCompanies = pickerCompany && !activeCompanies.some((company) => company.id === pickerCompany.id)
    ? [pickerCompany, ...activeCompanies]
    : activeCompanies;
  const pickerBusy = actions.add.isPending || companyActions.create.isPending || companyActions.remove.isPending;

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
        description="Manage GC App one trip at a time: availability, people, documents, and announcements. Paused trips stay here so you can restore them."
        actions={(
          <Button type="button" leftIcon={<Plus className="h-4 w-4" />} onClick={openPicker}>
            Add group to GC App
          </Button>
        )}
      />

      <Card className="overflow-visible border-slate-200/80 shadow-[0_8px_30px_-24px_rgba(15,23,42,0.45)]">
        <CardContent className="grid gap-3 p-4 sm:p-5 md:grid-cols-[minmax(0,1fr)_18rem] md:items-end">
          <Input
            label="Search GC App trips"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Group name or destination"
            leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
          />
          <GcSelect
            id="gc-group-availability"
            label="App availability"
            value={availability}
            options={APP_AVAILABILITY_OPTIONS}
            onChange={(nextAvailability) => {
              setAvailability(nextAvailability as GcAppAvailability | "all");
              setPage(1);
            }}
          />
        </CardContent>
      </Card>

      {groups.isError && groups.data && <GcAlert message="The trip list could not be refreshed. The last loaded data is shown; refresh before making changes." />}
      {groups.isLoading ? (
        <Card><GcLoadingRows count={3} /></Card>
      ) : groups.isError && !groups.data ? (
        <Card><CardContent className="space-y-3 p-5"><GcAlert message="GC App groups could not be loaded." /><Button type="button" variant="secondary" size="sm" onClick={() => void groups.refetch()}>Retry</Button></CardContent></Card>
      ) : groups.data?.items.length === 0 ? (
        <EmptyState
          icon={<Smartphone className="h-5 w-5" aria-hidden="true" />}
          title="No GC App trips found"
          description={search || availability !== "all" ? "Adjust the search or app availability filter." : "Add a passport group to set up its trip in GC App. Its collection link can be open or closed."}
          action={!search && availability === "all" ? { label: "Add group to GC App", onClick: openPicker } : undefined}
        />
      ) : (
        <div className="space-y-4">
          {groups.data?.items.map((group) => (
            <GroupControlCard
              key={group.id}
              group={group}
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
        description="Choose a non-archived group, whether its collection link is open or closed. Adding a new trip enables app access immediately for Passenger, Client Manager, and Coordinator roles. Review permissions and dates in Access & features."
        onClose={closePicker}
        closeDisabled={pickerBusy}
        size="lg"
      >
        <div className="space-y-4">
          {pickerError && <GcAlert message={pickerError} />}
          <div className="space-y-4 rounded-xl border border-slate-200 p-4">
            <GcSelect
              id="gc-app-group-company"
              label="Assigned company/client"
              value={pickerCompanyId}
              onChange={(id) => {
                setPickerCompanyId(id);
                setPickerCompany(selectableCompanies.find((company) => company.id === id) ?? null);
              }}
              options={selectableCompanies.map((company) => ({ value: company.id, label: company.name }))}
              placeholder="Choose the group owner"
              searchable
              searchValue={companySearch}
              onSearchChange={(nextSearch) => {
                setCompanySearch(nextSearch);
                setCompanyPage(1);
              }}
              searchPlaceholder="Find company/client"
              loading={companies.isLoading}
              emptyMessage="No matching company/client"
            />
            {companies.isError && <p role="alert" className="text-xs text-red-700">Companies could not be loaded.</p>}
            <div className="flex gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50/70 p-2">
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
              <p className="p-6 text-center text-sm text-slate-500">No eligible non-archived groups found.</p>
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

    </div>
  );
}

function GroupControlCard({
  group,
}: {
  group: GcAppGroupControl;
}) {
  const availability = describeAppAvailability(group);
  return (
    <Card className={group.access_revoked_at ? "border-red-200" : undefined}>
      <CardContent className="space-y-5 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="truncate text-base font-semibold text-slate-900">{group.name}</h3>
              <Badge variant={availability.variant}>{availability.label}</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-500">{group.destination ?? "Destination not set"} · {group.company?.name ?? "Client not assigned"}</p>
            <p className="mt-2 text-sm text-slate-600">{availability.description}</p>
            <p className="mt-1 text-xs text-slate-500">
              Passport collection: {capitalize(group.lifecycle)} · App access: {group.access_starts_at ? formatGcDateTime(group.access_starts_at) : "Immediate"} – {group.access_expires_at ? formatGcDateTime(group.access_expires_at) : "No expiry"}
            </p>
          </div>
          <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:flex-wrap">
            <Link
              href={ROUTES.dashboard.gcAppGroup(group.id) as never}
              className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "col-span-2 justify-center sm:col-span-1")}
            >
              <Settings2 className="h-4 w-4" aria-hidden="true" />
              Open trip
            </Link>
          </div>
        </div>
        <dl className="grid gap-3 border-t border-slate-100 pt-4 text-sm sm:grid-cols-3">
          <Metric label="Active mobile users" value={group.active_mobile_users} />
          <Metric label="Synced devices" value={group.synced_device_count} />
          <Metric label="Last successful sync" value={group.last_successful_sync_at ? formatGcDateTime(group.last_successful_sync_at) : "Never"} />
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
