"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { Badge, Button, Input, PasswordInput } from "@/components/ui";
import { useDebounce } from "@/hooks/use-debounce";
import {
  useClientCompanies,
  useClientCompanyMutations,
  useGcGroupSearch,
} from "../hooks/use-gc-app-admin";
import type { ClientManagerAccount, ClientManagerInput, GcGroupReference } from "../types";
import { gcAppErrorMessage } from "../utils";
import { GcAlert, GcLoadingRows } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GcSelect } from "./gc-select";

const managerSchema = z.object({
  name: z.string().trim().min(2, "Enter the Client Manager's name."),
  email: z.string().trim().email("Enter a valid email address."),
  phone_number: z.string().trim().min(8, "Enter a valid mobile number.").max(32),
  company_id: z.string().min(1, "Select the assigned company/client."),
  temporary_password: z.string().optional(),
}).superRefine((data, context) => {
  if (data.temporary_password === undefined) return;
  const password = data.temporary_password;
  if (password.length < 10 || !/[A-Z]/.test(password) || !/[a-z]/.test(password) || !/\d/.test(password)) {
    context.addIssue({
      code: "custom",
      path: ["temporary_password"],
      message: "Use at least 10 characters with uppercase, lowercase, and a number.",
    });
  }
});

type ManagerFormValues = z.infer<typeof managerSchema>;

export function ClientManagerFormDialog({
  open,
  agencyId,
  manager,
  isPending,
  onClose,
  onSubmit,
}: {
  open: boolean;
  agencyId: string | null;
  manager: ClientManagerAccount | null;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (body: ClientManagerInput) => Promise<void>;
}) {
  const [groupSearch, setGroupSearch] = useState("");
  const [selectedGroups, setSelectedGroups] = useState<GcGroupReference[]>(manager?.assigned_groups ?? []);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [newCompanyName, setNewCompanyName] = useState("");
  const [companySearch, setCompanySearch] = useState("");
  const [createdCompany, setCreatedCompany] = useState<ClientManagerAccount["company"] | null>(null);
  const [companyError, setCompanyError] = useState<string | null>(null);
  const debouncedGroupSearch = useDebounce(groupSearch, 300);
  const debouncedCompanySearch = useDebounce(companySearch, 300);
  const companies = useClientCompanies(agencyId, debouncedCompanySearch, 1, 50);
  const companyMutations = useClientCompanyMutations(agencyId);
  const groups = useGcGroupSearch(
    agencyId,
    { page: 1, page_size: 50, search: debouncedGroupSearch },
    false,
    open,
  );
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<ManagerFormValues>({
    resolver: zodResolver(managerSchema),
    defaultValues: {
      name: manager?.name ?? "",
      email: manager?.email ?? "",
      phone_number: manager?.phone_number ?? "",
      company_id: manager?.company.id ?? "",
      temporary_password: manager ? undefined : "",
    },
  });
  const selectedIds = useMemo(() => new Set(selectedGroups.map((group) => group.id)), [selectedGroups]);
  const managerCompanyId = manager?.company.id;
  const managerCompanyName = manager?.company.name;
  const managerCompanyStatus = manager?.company.status;
  const companyOptions = useMemo(() => {
    const options = [...(companies.data?.items ?? [])];
    const extras = [
      createdCompany,
      managerCompanyId && managerCompanyName
        ? { id: managerCompanyId, name: managerCompanyName, status: managerCompanyStatus }
        : null,
    ];
    for (const company of extras) {
      if (company && !options.some((option) => option.id === company.id)) options.unshift(company);
    }
    return options;
  }, [companies.data?.items, createdCompany, managerCompanyId, managerCompanyName, managerCompanyStatus]);
  const companySelectOptions = useMemo(() => companyOptions.map((company) => ({
    value: company.id,
    label: company.name,
    description: company.status === "inactive" ? "Inactive company/client" : undefined,
    disabled: company.status === "inactive" && company.id !== manager?.company.id,
  })), [companyOptions, manager?.company.id]);
  const availableGroups = (groups.data?.items ?? []).filter(
    (group) => group.lifecycle !== "archived" && group.lifecycle !== "deleted" && !selectedIds.has(group.id),
  );

  const submit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      await onSubmit({
        ...values,
        temporary_password: manager ? undefined : values.temporary_password || undefined,
        group_ids: selectedGroups.map((group) => group.id),
      });
    } catch (error) {
      setSubmitError(gcAppErrorMessage(error, "The Client Manager account could not be saved."));
    }
  });

  return (
    <GcDialog
      open={open}
      title={manager ? "Edit Client Manager" : "Create Client Manager"}
      description="Access is limited to the explicitly assigned company and groups."
      onClose={onClose}
      closeDisabled={isPending || isSubmitting}
      size="xl"
      footer={(
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={isPending || isSubmitting}>Cancel</Button>
          <Button type="submit" form="client-manager-form" isLoading={isPending || isSubmitting}>
            {manager ? "Save changes" : "Create account"}
          </Button>
        </>
      )}
    >
      <form id="client-manager-form" className="space-y-5" onSubmit={submit} noValidate>
        <section className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4 sm:p-5" aria-labelledby="manager-identity-heading">
          <div className="mb-4">
            <h3 id="manager-identity-heading" className="text-sm font-semibold text-slate-950">Account identity</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">These details identify the manager in the companion app and access audit.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
          <Input label="Name" required error={errors.name?.message} {...register("name")} />
          <Input label="Email" type="email" required error={errors.email?.message} {...register("email")} />
          <Input
            label="Mobile number"
            type="tel"
            required
            hint="Include the country code used for this contact."
            error={errors.phone_number?.message}
            {...register("phone_number")}
          />
          <div className="space-y-3">
            <Controller
              name="company_id"
              control={control}
              render={({ field }) => (
                <GcSelect
                  id="client-manager-company"
                  label="Assigned company/client *"
                  value={field.value}
                  options={companySelectOptions}
                  onChange={field.onChange}
                  placeholder="Choose a company/client"
                  searchable
                  searchValue={companySearch}
                  onSearchChange={setCompanySearch}
                  searchPlaceholder="Find company/client"
                  loading={companies.isLoading}
                  emptyMessage="No matching company/client"
                  error={errors.company_id?.message}
                />
              )}
            />
            {companies.isError && <p role="alert" className="text-xs text-red-600">Companies could not be loaded.</p>}
            {companies.data?.has_next && (
              <p className="text-xs text-slate-500">More matches are available. Refine the company/client search.</p>
            )}
            <div className="flex gap-2 rounded-xl border border-dashed border-slate-300 bg-white p-2">
              <Input
                aria-label="New company or client name"
                value={newCompanyName}
                onChange={(event) => setNewCompanyName(event.target.value)}
                placeholder="New company/client name"
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                isLoading={companyMutations.create.isPending}
                disabled={!newCompanyName.trim()}
                onClick={() => {
                  const name = newCompanyName.trim();
                  if (!name) return;
                  setCompanyError(null);
                  void companyMutations.create.mutateAsync(name).then((company) => {
                    setCreatedCompany(company);
                    setValue("company_id", company.id, { shouldDirty: true, shouldValidate: true });
                    setNewCompanyName("");
                  }).catch((error: unknown) => {
                    setCompanyError(gcAppErrorMessage(error, "The company/client could not be created."));
                  });
                }}
              >
                Add company
              </Button>
            </div>
            {companyError && <p role="alert" className="text-xs text-red-600">{companyError}</p>}
          </div>
        </div>
        </section>

        <fieldset className="space-y-3 rounded-xl border border-slate-200 p-4">
          <legend className="px-1 text-sm font-semibold text-slate-900">Explicit group assignments</legend>
          <div className="flex flex-wrap gap-2">
            {selectedGroups.length === 0 && <p className="text-sm text-slate-500">No groups assigned yet.</p>}
            {selectedGroups.map((group) => (
              <Badge key={group.id} variant="secondary" className="gap-2 py-1">
                {group.name}
                <button
                  type="button"
                  className="rounded-full p-0.5 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"
                  onClick={() => setSelectedGroups((current) => current.filter((item) => item.id !== group.id))}
                  aria-label={`Remove ${group.name} assignment`}
                >
                  <X className="h-3 w-3" aria-hidden="true" />
                </button>
              </Badge>
            ))}
          </div>
          <Input
            label="Find a group"
            value={groupSearch}
            onChange={(event) => setGroupSearch(event.target.value)}
            leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
            placeholder="Search active or closed groups"
          />
          <div className="max-h-44 overflow-y-auto rounded-xl border border-slate-200 bg-white">
            {groups.isLoading ? (
              <GcLoadingRows count={2} />
            ) : groups.isError ? (
              <p role="alert" className="p-3 text-sm text-red-600">Groups could not be loaded.</p>
            ) : availableGroups.length === 0 ? (
              <p className="p-3 text-sm text-slate-500">No assignable groups found.</p>
            ) : availableGroups.map((group) => (
              <button
                key={group.id}
                type="button"
                className="flex min-h-11 w-full items-center justify-between gap-4 border-b border-slate-100 px-3 py-2 text-left last:border-0 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-600"
                onClick={() => setSelectedGroups((current) => [...current, group])}
              >
                <span>
                  <span className="block text-sm font-medium text-slate-800">{group.name}</span>
                  <span className="block text-xs text-slate-500">{group.destination ?? "Destination not set"}</span>
                </span>
                <span className="text-xs font-medium text-blue-700">Assign</span>
              </button>
            ))}
          </div>
        </fieldset>

        {!manager && (
          <fieldset className="space-y-4 rounded-2xl border border-slate-200 p-4 sm:p-5">
            <legend className="px-1 text-sm font-semibold text-slate-900">Initial password</legend>
            <div className="flex items-start gap-3 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
              <span className="rounded-lg bg-white p-2 text-blue-700 shadow-sm"><KeyRound className="h-4 w-4" aria-hidden="true" /></span>
              <span><span className="block text-sm font-semibold text-slate-900">Set the sign-in password</span><span className="mt-1 block text-xs leading-5 text-slate-600">Share it through your approved channel. The manager can use it immediately.</span></span>
            </div>
            <PasswordInput
              label="Initial password"
              autoComplete="new-password"
              required
              error={errors.temporary_password?.message}
              {...register("temporary_password")}
            />
          </fieldset>
        )}

        {submitError && <GcAlert message={submitError} />}
      </form>
    </GcDialog>
  );
}
