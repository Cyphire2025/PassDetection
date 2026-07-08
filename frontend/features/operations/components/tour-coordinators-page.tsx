"use client";

import { FormEvent, useState } from "react";
import { Mail, UserPlus, UsersRound } from "lucide-react";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import {
  useCreateTourCoordinator,
  useTourCoordinators,
} from "../hooks/use-operations";

export function TourCoordinatorsPage() {
  const { data: coordinators = [], isLoading, error } = useTourCoordinators();
  const createCoordinator = useCreateTourCoordinator();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFormError(null);

    if (form.password.length < 8) {
      setFormError("Password must be at least 8 characters.");
      return;
    }

    try {
      await createCoordinator.mutateAsync(form);
      setForm({ full_name: "", email: "", password: "" });
    } catch {
      setFormError("Could not create coordinator. Check whether the email already exists.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tour Coordinators"
        description="Create field coordinator accounts for tour attendance operations."
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Coordinator accounts could not be loaded.
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <UserPlus className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Create Coordinator</h2>
                <p className="text-sm text-slate-500">Coordinators can work only on assigned tour groups.</p>
              </div>
            </div>

            <form className="space-y-4" onSubmit={handleSubmit}>
              <Input
                label="Full name"
                value={form.full_name}
                onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                required
              />
              <Input
                label="Email"
                type="email"
                value={form.email}
                onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                required
              />
              <Input
                label="Temporary password"
                type="password"
                value={form.password}
                onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
                required
              />
              {formError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{formError}</div>}
              <Button type="submit" className="w-full" isLoading={createCoordinator.isPending}>
                Create Coordinator
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card className="min-w-0">
          <CardContent className="p-0">
            <div className="flex items-center justify-between border-b border-slate-200 p-5">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <UsersRound className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Coordinators</h2>
                  <p className="text-sm text-slate-500">Field accounts available for group assignment.</p>
                </div>
              </div>
              <Badge variant="secondary">{coordinators.length}</Badge>
            </div>

            {isLoading ? (
              <div className="space-y-3 p-5">
                {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-12 rounded-lg" />)}
              </div>
            ) : coordinators.length === 0 ? (
              <div className="px-5 py-10 text-sm text-slate-500">No coordinators created yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] text-left text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Name</th>
                      <th className="px-5 py-3">Email</th>
                      <th className="px-5 py-3">Groups</th>
                      <th className="px-5 py-3">Passengers</th>
                      <th className="px-5 py-3">Last Login</th>
                      <th className="px-5 py-3">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {coordinators.map((coordinator) => (
                      <tr key={coordinator.id} className="hover:bg-slate-50">
                        <td className="px-5 py-4 font-medium text-slate-900">{coordinator.full_name}</td>
                        <td className="px-5 py-4 text-slate-600">
                          <span className="inline-flex items-center gap-2">
                            <Mail className="h-4 w-4 text-slate-400" aria-hidden="true" />
                            {coordinator.email}
                          </span>
                        </td>
                        <td className="px-5 py-4 text-slate-600">{coordinator.assigned_groups_count}</td>
                        <td className="px-5 py-4 text-slate-600">{coordinator.assigned_passengers_count}</td>
                        <td className="px-5 py-4 text-slate-600">{coordinator.last_login_at ?? "Never"}</td>
                        <td className="px-5 py-4">
                          <Badge variant={coordinator.is_active ? "success" : "outline"}>
                            {coordinator.is_active ? "active" : "inactive"}
                          </Badge>
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
    </div>
  );
}
