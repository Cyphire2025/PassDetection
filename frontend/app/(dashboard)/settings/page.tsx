"use client";

import type React from "react";
import { Archive, Bell, Database, LockKeyhole, ScanText, UserCog } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Badge, Card, CardContent } from "@/components/ui";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { formatDateTime } from "@/lib/utils/format";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  agency_admin: "Agency Admin",
  agency_staff: "Manager",
};

export default function SettingsPage() {
  const user = useAuthStore(selectUser);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Operational defaults and account-level controls for passport processing."
      />

      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <UserCog className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Account</h2>
                <p className="text-sm text-slate-500">Signed-in user and access scope.</p>
              </div>
            </div>

            <div className="space-y-4 text-sm">
              <SettingRow label="Name" value={user?.full_name ?? "Unavailable"} />
              <SettingRow label="Email" value={user?.email ?? "Unavailable"} />
              <SettingRow label="Role" value={user ? ROLE_LABELS[user.role] ?? user.role : "Unavailable"} />
              <SettingRow label="Last login" value={user?.last_login_at ? formatDateTime(user.last_login_at) : "Not recorded"} />
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-6 md:grid-cols-2">
          <SettingCard
            icon={<LockKeyhole className="h-5 w-5" />}
            title="Access Control"
            badge="Active"
            lines={[
              "Super admin and agency admin can view agency-wide records.",
              "Manager accounts are scoped to groups they create.",
              "Managers can work on upload links and passport reviews only.",
            ]}
          />
          <SettingCard
            icon={<Archive className="h-5 w-5" />}
            title="Archive Policy"
            badge="Soft Delete"
            lines={[
              "Archived groups are hidden from active upload links and passport queues.",
              "Archived submissions remain included in total passport history.",
              "Archived groups can be restored from the Upload Links archive section.",
            ]}
          />
          <SettingCard
            icon={<ScanText className="h-5 w-5" />}
            title="OCR Review"
            badge="Conservative"
            lines={[
              "Low-confidence extraction is routed to review instead of auto-confirming.",
              "MRZ and field validation are combined before confidence is shown.",
              "Office users can re-extract when image quality or OCR output is poor.",
            ]}
          />
          <SettingCard
            icon={<Database className="h-5 w-5" />}
            title="Data Handling"
            badge="Retained"
            lines={[
              "Uploaded images stay attached to the passport review record.",
              "Client email and phone duplicates are blocked within the same group.",
              "Exports remain group-scoped to avoid mixing unrelated client batches.",
            ]}
          />
          <SettingCard
            icon={<Bell className="h-5 w-5" />}
            title="Notifications"
            badge="Enabled"
            lines={[
              "Client submissions create office notifications.",
              "Unread notification state is tracked per agency workflow.",
              "Audit logs record exports, confirmations, and extraction actions.",
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-slate-100 pb-3 last:border-b-0 last:pb-0">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-medium text-slate-900">{value}</span>
    </div>
  );
}

function SettingCard({
  icon,
  title,
  badge,
  lines,
}: {
  icon: React.ReactNode;
  title: string;
  badge: string;
  lines: string[];
}) {
  return (
    <Card>
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
              {icon}
            </span>
            <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          </div>
          <Badge variant="secondary">{badge}</Badge>
        </div>
        <ul className="space-y-2 text-sm text-slate-600">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
