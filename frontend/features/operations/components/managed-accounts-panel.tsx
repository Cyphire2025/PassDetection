"use client";

import { Badge, Card, CardContent, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { useManagedAccounts } from "../hooks/use-operations";
import { ManagedAccountControls } from "./managed-account-controls";

export function ManagedAccountsPanel() {
  const { data: accounts = [], isLoading, error } = useManagedAccounts();

  return (
    <Card>
      <CardContent className="p-0">
        <div className="border-b border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900">Account security</h2>
          <p className="mt-1 text-sm text-slate-500">Reset credentials, revoke sessions, and remove access without exposing stored passwords.</p>
        </div>
        {error ? (
          <p className="p-5 text-sm text-red-700">Account controls could not be loaded.</p>
        ) : isLoading ? (
          <div className="space-y-3 p-5"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[980px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-5 py-3">Account</th><th className="px-5 py-3">Role</th><th className="px-5 py-3">Agency</th><th className="px-5 py-3">Last login</th><th className="px-5 py-3">Status</th><th className="px-5 py-3 text-right">Controls</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {accounts.map((account) => (
                  <tr key={account.id}>
                    <td className="px-5 py-4"><div className="font-medium text-slate-900">{account.full_name}</div><div className="text-xs text-slate-500">{account.email}</div></td>
                    <td className="px-5 py-4 text-slate-600">{account.role === "agency_staff" ? "Manager" : "Coordinator"}</td>
                    <td className="px-5 py-4 text-slate-600">{account.agency_name ?? "Unassigned"}</td>
                    <td className="px-5 py-4 text-slate-600">{account.last_login_at ? formatDateTime(account.last_login_at) : "Never"}</td>
                    <td className="px-5 py-4"><Badge variant={account.is_active ? "success" : "outline"}>{account.is_active ? "Active" : "Inactive"}</Badge></td>
                    <td className="px-5 py-4"><ManagedAccountControls accountId={account.id} accountName={account.full_name} isActive={account.is_active} allowDelete={account.role === "agency_coordinator"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
