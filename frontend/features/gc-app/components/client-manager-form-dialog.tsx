"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
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
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

const managerSchema = z.object({
  name: z.string().trim().min(2, "Enter the Client Manager's name."),
  email: z.string().trim().email("Enter a valid email address."),
  phone_number: z.string().trim().min(7, "Enter a valid mobile number.").max(32),
  company_id: z.string().min(1, "Select the assigned company/client."),
  activation_method: z.enum(["invitation", "temporary_password"]),
  temporary_password: z.string().optional(),
  force_password_change: z.boolean(),
}).superRefine((data, context) => {
  if (data.activation_method !== "temporary_password") return;
  const password = data.temporary_password ?? "";
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
    formState: { errors },
  } = useForm<ManagerFormValues>({
    resolver: zodResolver(managerSchema),
    defaultValues: {
      name: manager?.name ?? "",
      email: manager?.email ?? "",
      phone_number: manager?.phone_number ?? "",
      company_id: manager?.company.id ?? "",
      activation_method: "invitation",
      temporary_password: "",
      force_password_change: manager?.force_password_change ?? true,
    },
  });
  const activationMethod = useWatch({ control, name: "activation_method" });

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
  const availableGroups = (groups.data?.items ?? []).filter(
    (group) => group.lifecycle !== "archived" && group.lifecycle !== "deleted" && !selectedIds.has(group.id),
  );

  const submit = handleSubmit(async (values) => {
    setSubmitError(null);
    try {
      await onSubmit({
        ...values,
        activation_method: manager ? undefined : values.activation_method,
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
      closeDisabled={isPending}
      size="xl"
      footer={(
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button type="submit" form="client-manager-form" isLoading={isPending}>
            {manager ? "Save changes" : "Create account"}
          </Button>
        </>
      )}
    >
      <form id="client-manager-form" className="space-y-6" onSubmit={submit} noValidate>
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
          <div className="flex flex-col gap-1.5">
            <label htmlFor="client-manager-company" className="text-sm font-medium text-slate-700">
              Assigned company/client <span className="text-red-500" aria-hidden="true">*</span>
            </label>
            <Input
              aria-label="Search company or client"
              value={companySearch}
              onChange={(event) => setCompanySearch(event.target.value)}
              placeholder="Search company/client"
              leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
            />
            <select
              id="client-manager-company"
              className="h-9 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-600"
              aria-invalid={Boolean(errors.company_id)}
              {...register("company_id")}
            >
              <option value="">Select company/client</option>
              {companyOptions
                .filter((company) => company.status !== "inactive" || company.id === manager?.company.id)
                .map((company) => (
                <option key={company.id} value={company.id} disabled={company.status === "inactive"}>
                  {company.name}{company.status === "inactive" ? " (inactive)" : ""}
                </option>
              ))}
            </select>
            {companies.isError && <p role="alert" className="text-xs text-red-600">Companies could not be loaded.</p>}
            {companies.data?.has_next && (
              <p className="text-xs text-slate-500">More matches are available. Refine the company/client search.</p>
            )}
            {errors.company_id && <p role="alert" className="text-xs text-red-600">{errors.company_id.message}</p>}
            <div className="mt-2 flex gap-2">
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
                Add
              </Button>
            </div>
            {companyError && <p role="alert" className="text-xs text-red-600">{companyError}</p>}
          </div>
        </div>

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
          <div className="max-h-40 overflow-y-auto rounded-lg border border-slate-200">
            {groups.isLoading ? (
              <p className="p-3 text-sm text-slate-500">Searching groups…</p>
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
          <fieldset className="space-y-4 rounded-xl border border-slate-200 p-4">
            <legend className="px-1 text-sm font-semibold text-slate-900">Initial account activation</legend>
            <label className="flex min-h-11 items-start gap-3 rounded-lg border border-slate-200 p-3">
              <input type="radio" value="invitation" className="mt-1" {...register("activation_method")} />
              <span><span className="block text-sm font-medium text-slate-800">Invitation flow</span><span className="text-xs text-slate-500">Send a single-use activation invitation through the configured channel.</span></span>
            </label>
            <label className="flex min-h-11 items-start gap-3 rounded-lg border border-slate-200 p-3">
              <input type="radio" value="temporary_password" className="mt-1" {...register("activation_method")} />
              <span><span className="block text-sm font-medium text-slate-800">Temporary password</span><span className="text-xs text-slate-500">Create a temporary password and require a change at first login.</span></span>
            </label>
            {activationMethod === "temporary_password" && (
              <PasswordInput
                label="Temporary password"
                autoComplete="new-password"
                error={errors.temporary_password?.message}
                {...register("temporary_password")}
              />
            )}
          </fieldset>
        )}

        <label className="flex min-h-11 items-center gap-3 rounded-xl border border-slate-200 px-4 py-3 text-sm text-slate-700">
          <input type="checkbox" className="h-4 w-4 rounded border-slate-300" {...register("force_password_change")} />
          Force password change at next login
        </label>

        {submitError && <GcAlert message={submitError} />}
      </form>
    </GcDialog>
  );
}
