"use client";

import { AlertTriangle, Building2, Search, Trash2 } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import type { GcGroupPicker } from "../hooks/use-gc-group-picker";
import { gcAppErrorMessage } from "../utils";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

export function AddGcAppGroupDialog({ picker }: { picker: GcGroupPicker }) {
  const { pickerOpen, closePicker, pickerBusy, pickerError, pickerCompanyId, setPickerCompanyId,
    setPickerCompany, selectableCompanies, companySearch, setCompanySearch, setCompanyPage,
    companies, newCompanyName, setNewCompanyName, setPickerError, companyActions,
    activeCompanies, setPendingCompanyRemoval, setCompanyRemovalConfirmation,
    pendingCompanyRemoval, companyRemovalConfirmation, removeCompany, pickerSearch,
    setPickerSearch, setPickerPage, candidates, actions, pickerCompany, setPickerOpen } = picker;
  return (
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

  );
}
