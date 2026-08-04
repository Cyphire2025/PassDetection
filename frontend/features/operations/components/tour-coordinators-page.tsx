"use client";

import { FormEvent, useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";
import type React from "react";
import Link from "next/link";
import { ArrowLeft, CalendarClock, CheckCircle2, Mail, Plus, UserPlus, UsersRound, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Input, PasswordInput, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import {
  useCreateTourCoordinator,
  useTourCoordinators,
} from "../hooks/use-operations";
import { ManagedAccountControls } from "./managed-account-controls";
import {
  OperationsEmptyState,
  OperationsErrorNotice,
  OperationsPageHeader,
  OperationsSummaryItem,
  OperationsSummaryStrip,
  OperationsToolbar,
} from "./operations-workspace-ui";

export function TourCoordinatorsPage() {
  const { data: coordinators = [], isLoading, error } = useTourCoordinators();
  const createCoordinator = useCreateTourCoordinator();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [formError, setFormError] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const visibleCoordinators = useMemo(() => {
    const normalized = deferredQuery.trim().toLocaleLowerCase();
    if (!normalized) return coordinators;
    return coordinators.filter((coordinator) => [
      coordinator.full_name,
      coordinator.email,
      coordinator.is_active ? "active" : "inactive",
    ].some((value) => value.toLocaleLowerCase().includes(normalized)));
  }, [coordinators, deferredQuery]);
  const activeCount = coordinators.filter((coordinator) => coordinator.is_active).length;
  const coveredGroups = coordinators.reduce((total, coordinator) => total + coordinator.assigned_groups_count, 0);
  const neverLoggedIn = coordinators.filter((coordinator) => !coordinator.last_login_at).length;

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    if (form.password.length < 10 || !/[A-Z]/.test(form.password) || !/[a-z]/.test(form.password) || !/\d/.test(form.password)) {
      setFormError("Use at least 10 characters with uppercase, lowercase, and a number.");
      return;
    }

    try {
      await createCoordinator.mutateAsync(form);
      setForm({ full_name: "", email: "", password: "" });
      setShowCreateDialog(false);
    } catch {
      setFormError("Could not create coordinator. Check whether the email already exists.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <OperationsPageHeader
        eyebrow="Tour Ops access"
        title="Tour Coordinators"
        description="Manage restricted field accounts, review operational coverage, and keep coordinator access ready for attendance scanning."
        icon={UsersRound}
        context={<span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" />{activeCount} active accounts</span>}
        actions={(
          <>
            <Link href={ROUTES.dashboard.tourOperationsGroupAssignments as never} className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Tour Ops</Link>
            <Button type="button" onClick={() => setShowCreateDialog(true)} className="bg-white text-slate-950 hover:bg-sky-50 active:bg-sky-100"><Plus className="h-4 w-4" aria-hidden="true" />Create coordinator</Button>
          </>
        )}
      />

      {error && (
        <OperationsErrorNotice>Coordinator accounts could not be refreshed. Previously loaded accounts remain available where possible.</OperationsErrorNotice>
      )}

      <OperationsSummaryStrip label="Coordinator account summary">
        {isLoading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />) : (
          <>
            <OperationsSummaryItem label="Accounts" value={coordinators.length} helper="coordinators" icon={UsersRound} />
            <OperationsSummaryItem label="Active" value={activeCount} helper="can sign in" icon={CheckCircle2} tone={activeCount === coordinators.length && coordinators.length > 0 ? "success" : "default"} />
            <OperationsSummaryItem label="Group coverage" value={coveredGroups} helper="assignments" icon={UserPlus} />
            <OperationsSummaryItem label="Never signed in" value={neverLoggedIn} helper="accounts" icon={CalendarClock} tone={neverLoggedIn > 0 ? "attention" : "success"} />
          </>
        )}
      </OperationsSummaryStrip>

      <div className="grid gap-6">
        <Card className="min-w-0">
          <CardContent className="p-0">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-600 ring-1 ring-slate-200">
                  <UsersRound className="h-5 w-5" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-slate-900">Coordinators</h2>
                  <p className="mt-0.5 text-sm text-slate-500">Field accounts available for group assignment.</p>
                </div>
              </div>
              <Badge variant="secondary" className="px-3 py-1">{coordinators.length} total</Badge>
            </div>

            <OperationsToolbar query={query} onQueryChange={setQuery} searchLabel="Search coordinators" placeholder="Search coordinator, email, or status" resultLabel={`${visibleCoordinators.length} of ${coordinators.length} accounts`} />

            {isLoading ? (
              <div className="space-y-3 p-5">
                {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-12 rounded-lg" />)}
              </div>
            ) : coordinators.length === 0 ? (
              <OperationsEmptyState title="No coordinator accounts yet" description="Create the first restricted field account, then assign it to one or more Tour Ops groups." action={<Button type="button" onClick={() => setShowCreateDialog(true)}><Plus className="h-4 w-4" aria-hidden="true" />Create coordinator</Button>} />
            ) : visibleCoordinators.length === 0 ? (
              <OperationsEmptyState filtered title="No coordinators match this search" description="Search by name, email, or account status, or clear the search to restore all accounts." action={<button type="button" onClick={() => setQuery("")} className="text-sm font-semibold text-blue-700 hover:text-blue-900">Clear search</button>} />
            ) : (
              <div className="overflow-x-auto overflow-y-visible">
                <table className="w-full min-w-[760px] table-fixed text-left text-sm">
                  <colgroup>
                    <col className="w-[34%]" />
                    <col className="w-[18%]" />
                    <col className="w-[22%]" />
                    <col className="w-[14%]" />
                    <col className="w-[12%]" />
                  </colgroup>
                  <thead className="border-b border-slate-200 bg-slate-50/80 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-6 py-3.5">Coordinator</th>
                      <th className="px-5 py-3.5">Coverage</th>
                      <th className="px-5 py-3.5">Last login</th>
                      <th className="px-5 py-3.5">Status</th>
                      <th className="px-6 py-3.5 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {visibleCoordinators.map((coordinator) => (
                      <tr key={coordinator.id} className="group hover:bg-slate-50/80">
                        <td className="px-6 py-4">
                          <div className="flex min-w-0 items-center gap-3">
                            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600 ring-1 ring-slate-200">
                              {initials(coordinator.full_name)}
                            </span>
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-slate-900">{coordinator.full_name}</div>
                              <div className="mt-1 flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
                                <Mail className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                                <span className="truncate">{coordinator.email}</span>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-5 py-4">
                          <div className="flex flex-wrap gap-2">
                            <MetricPill icon={<UsersRound className="h-3.5 w-3.5" aria-hidden="true" />} value={coordinator.assigned_groups_count} label="groups" />
                          </div>
                        </td>
                        <td className="px-5 py-4 text-slate-600">
                          <span className="inline-flex max-w-full items-center gap-2">
                            <CalendarClock className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                            <span className="truncate">{formatLastLogin(coordinator.last_login_at)}</span>
                          </span>
                        </td>
                        <td className="px-5 py-4">
                          <Badge variant={coordinator.is_active ? "success" : "outline"} dot>
                            {coordinator.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>
                        <td className="px-6 py-4">
                          <ManagedAccountControls
                            accountId={coordinator.id}
                            accountName={coordinator.full_name}
                            isActive={coordinator.is_active}
                            allowDelete
                          />
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

      {showCreateDialog && (
        <CreateCoordinatorDialog
          form={form}
          formError={formError}
          isLoading={createCoordinator.isPending}
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

function CreateCoordinatorDialog({
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
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isLoading) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
      if (controls.length === 0) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [isLoading]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !isLoading) onClose(); }}>
      <Card ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} className="w-full max-w-lg overflow-hidden shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600 ring-1 ring-blue-100">
                <UserPlus className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 id={titleId} className="text-base font-semibold text-slate-900">Create Coordinator</h2>
                <p className="mt-0.5 text-sm leading-5 text-slate-500">Create a restricted field login for assigned groups only.</p>
              </div>
            </div>
            <button type="button" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose} aria-label="Close create coordinator dialog">
              <X className="h-5 w-5" aria-hidden="true" />
              <span className="sr-only">Close</span>
            </button>
          </div>

          <form className="space-y-4" onSubmit={onSubmit}>
            <Input
              label="Full name"
              placeholder="Example: Raj Sharma"
              value={form.full_name}
              onChange={(event) => onFormChange((current) => ({ ...current, full_name: event.target.value }))}
              required
            />
            <Input
              label="Email"
              type="email"
              placeholder="coordinator@company.com"
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
              Password must include uppercase, lowercase, and a number. The account can be reset later by an admin.
            </p>
            {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
            <div className="flex justify-end gap-3 pt-1">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>Create Coordinator</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "C";
}

function formatLastLogin(value: string | null | undefined) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Never";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function MetricPill({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: number;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 shadow-sm">
      <span className="text-slate-400">{icon}</span>
      <span className="text-slate-900">{value}</span>
      <span className="text-slate-500">{label}</span>
    </span>
  );
}
