"use client";

import { FormEvent, useState } from "react";
import { ShieldCheck, UserPlus, Users } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { useCreateManager, useManagers } from "@/features/operations/hooks/use-operations";

export default function AdminPage() {
  const { data: managers = [], isLoading, error } = useManagers();
  const createManager = useCreateManager();
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
      await createManager.mutateAsync(form);
      setForm({ full_name: "", email: "", password: "" });
    } catch {
      setFormError("Could not create manager. Check whether the email already exists.");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Admin"
        description="Create manager accounts and control who can work on group submissions."
      />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Manager administration is unavailable for this account.
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <UserPlus className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Create Manager</h2>
                <p className="text-sm text-slate-500">Managers can create groups and see only their own work.</p>
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
              <Button type="submit" className="w-full" disabled={createManager.isPending}>
                {createManager.isPending ? "Creating Manager" : "Create Manager"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-0">
            <div className="flex items-center justify-between border-b border-slate-200 p-5">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <Users className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Managers</h2>
                  <p className="text-sm text-slate-500">Limited accounts scoped to self-created groups.</p>
                </div>
              </div>
              <Badge variant="secondary">{managers.length}</Badge>
            </div>

            {isLoading ? (
              <div className="space-y-3 p-5">
                <Skeleton className="h-12 w-full rounded-lg" />
                <Skeleton className="h-12 w-full rounded-lg" />
                <Skeleton className="h-12 w-full rounded-lg" />
              </div>
            ) : managers.length === 0 ? (
              <div className="px-5 py-10 text-sm text-slate-500">No managers created yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-5 py-3">Name</th>
                      <th className="px-5 py-3">Email</th>
                      <th className="px-5 py-3">Access</th>
                      <th className="px-5 py-3">Created</th>
                      <th className="px-5 py-3">Last Login</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {managers.map((manager) => (
                      <tr key={manager.id} className="hover:bg-slate-50/70">
                        <td className="px-5 py-4 font-medium text-slate-900">{manager.full_name}</td>
                        <td className="px-5 py-4 text-slate-600">{manager.email}</td>
                        <td className="px-5 py-4">
                          <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
                            <ShieldCheck className="h-3.5 w-3.5" /> Own groups only
                          </span>
                        </td>
                        <td className="px-5 py-4 text-slate-600">{formatDateTime(manager.created_at)}</td>
                        <td className="px-5 py-4 text-slate-600">
                          {manager.last_login_at ? formatDateTime(manager.last_login_at) : "Never"}
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
