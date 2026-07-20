"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, LockKeyhole, Save, Trash2, UserCog } from "lucide-react";
import { PageHeader } from "@/components/shared";
import { Badge, Button, Card, CardContent, ConfirmDialog, Input, Skeleton } from "@/components/ui";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { formatDateTime } from "@/lib/utils/format";

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  agency_admin: "Agency Admin",
  agency_manager: "Manager",
  agency_staff: "Staff",
  agency_coordinator: "Coordinator",
};

type PurgePassportDataResponse = {
  deleted_client_groups: number;
  deleted_passport_submissions: number;
  deleted_processing_jobs: number;
  deleted_notifications: number;
  deleted_audit_logs: number;
  deleted_storage_objects: number;
  deleted_whatsapp_broadcast_groups: number;
  deleted_whatsapp_recipients: number;
  deleted_whatsapp_support_contacts: number;
  deleted_whatsapp_message_logs: number;
  deleted_whatsapp_delivery_states: number;
};

type PlatformSettings = {
  platform_name: string;
  require_client_email: boolean;
  require_client_phone: boolean;
  duplicate_contact_policy: "block_same_group" | "allow" | "block_all";
  default_group_status: "active" | "closed";
  auto_archive_closed_groups_days: number;
  passport_data_retention_days: number;
  mrz_review_threshold: number;
  allow_manager_group_creation: boolean;
  audit_log_retention_days: number;
  updated_at: string | null;
};

const DELETE_CONFIRMATION = "DELETE ALL DATA";
const DEFAULT_SETTINGS: PlatformSettings = {
  platform_name: "Global Connects Dashboard",
  require_client_email: false,
  require_client_phone: false,
  duplicate_contact_policy: "block_same_group",
  default_group_status: "active",
  auto_archive_closed_groups_days: 90,
  passport_data_retention_days: 365,
  mrz_review_threshold: 0.85,
  allow_manager_group_creation: true,
  audit_log_retention_days: 365,
  updated_at: null,
};

export default function SettingsPage() {
  const user = useAuthStore(selectUser);
  const [settings, setSettings] = useState<PlatformSettings>(DEFAULT_SETTINGS);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [isPurging, setIsPurging] = useState(false);
  const [purgeError, setPurgeError] = useState<string | null>(null);
  const [purgeResult, setPurgeResult] = useState<PurgePassportDataResponse | null>(null);
  const [isPurgeDialogOpen, setIsPurgeDialogOpen] = useState(false);

  const canPurge = user?.role === "super_admin" || user?.role === "agency_admin";
  const isConfirmed = confirmation === DELETE_CONFIRMATION;

  useEffect(() => {
    let active = true;
    apiClient
      .get<PlatformSettings>(API_ENDPOINTS.admin.settings)
      .then(({ data }) => {
        if (active) setSettings(data);
      })
      .catch(() => {
        if (active) setSaveError("Could not load platform settings.");
      })
      .finally(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const updateSetting = <K extends keyof PlatformSettings>(key: K, value: PlatformSettings[K]) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const handleSave = async () => {
    setIsSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const payload = {
        platform_name: settings.platform_name,
        require_client_email: settings.require_client_email,
        require_client_phone: settings.require_client_phone,
        duplicate_contact_policy: settings.duplicate_contact_policy,
        default_group_status: settings.default_group_status,
        auto_archive_closed_groups_days: settings.auto_archive_closed_groups_days,
        passport_data_retention_days: settings.passport_data_retention_days,
        mrz_review_threshold: settings.mrz_review_threshold,
        allow_manager_group_creation: settings.allow_manager_group_creation,
        audit_log_retention_days: settings.audit_log_retention_days,
      };
      const { data } = await apiClient.put<PlatformSettings>(API_ENDPOINTS.admin.settings, payload);
      setSettings(data);
      setSaveMessage("Settings saved.");
    } catch {
      setSaveError("Could not save settings.");
    } finally {
      setIsSaving(false);
    }
  };

  const handlePurgePassportData = async () => {
    if (!canPurge || !isConfirmed || isPurging) return;

    setIsPurging(true);
    setPurgeError(null);
    setPurgeResult(null);
    try {
      const { data } = await apiClient.delete<PurgePassportDataResponse>(API_ENDPOINTS.admin.passportData);
      setPurgeResult(data);
      setConfirmation("");
      setIsPurgeDialogOpen(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not delete passport data.";
      setPurgeError(message);
    } finally {
      setIsPurging(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Configure platform defaults, access policy, retention, and review behavior."
      />

      <div className="grid gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card>
          <CardContent className="space-y-5 p-5">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                <UserCog className="h-5 w-5" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">Account</h2>
                <p className="text-sm text-slate-500">Signed-in admin and access scope.</p>
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

        <Card>
          <CardContent className="space-y-6 p-5">
            <div className="flex flex-col gap-3 border-b border-slate-100 pb-5 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                  <LockKeyhole className="h-5 w-5" />
                </span>
                <div>
                  <h2 className="text-base font-semibold text-slate-900">Platform Controls</h2>
                  <p className="text-sm text-slate-500">
                    {settings.updated_at ? `Last saved ${formatDateTime(settings.updated_at)}` : "Default settings loaded"}
                  </p>
                </div>
              </div>
              <Button type="button" onClick={handleSave} isLoading={isSaving} leftIcon={<Save className="h-4 w-4" />}>
                Save Settings
              </Button>
            </div>

            {isLoading ? (
              <div className="grid gap-4 md:grid-cols-2">
                <Skeleton className="h-24 w-full rounded-lg" />
                <Skeleton className="h-24 w-full rounded-lg" />
                <Skeleton className="h-24 w-full rounded-lg" />
                <Skeleton className="h-24 w-full rounded-lg" />
              </div>
            ) : (
              <div className="grid gap-5 md:grid-cols-2">
                <Input
                  label="Platform name"
                  value={settings.platform_name}
                  onChange={(event) => updateSetting("platform_name", event.target.value)}
                />

                <SelectSetting
                  label="Default new group status"
                  value={settings.default_group_status}
                  onChange={(value) => updateSetting("default_group_status", value as PlatformSettings["default_group_status"])}
                  options={[
                    ["active", "Active"],
                    ["closed", "Closed"],
                  ]}
                />

                <SelectSetting
                  label="Duplicate client contact policy"
                  value={settings.duplicate_contact_policy}
                  onChange={(value) =>
                    updateSetting("duplicate_contact_policy", value as PlatformSettings["duplicate_contact_policy"])
                  }
                  options={[
                    ["block_same_group", "Block duplicates in same group"],
                    ["block_all", "Block duplicates across platform"],
                    ["allow", "Allow duplicates"],
                  ]}
                />

                <NumberSetting
                  label="MRZ review threshold"
                  value={settings.mrz_review_threshold}
                  min={0}
                  max={1}
                  step={0.01}
                  onChange={(value) => updateSetting("mrz_review_threshold", value)}
                />

                <NumberSetting
                  label="Auto-archive closed groups after days"
                  value={settings.auto_archive_closed_groups_days}
                  min={1}
                  max={3650}
                  onChange={(value) => updateSetting("auto_archive_closed_groups_days", value)}
                />

                <NumberSetting
                  label="Passport data retention days"
                  value={settings.passport_data_retention_days}
                  min={1}
                  max={3650}
                  onChange={(value) => updateSetting("passport_data_retention_days", value)}
                />

                <NumberSetting
                  label="Audit log retention days"
                  value={settings.audit_log_retention_days}
                  min={1}
                  max={3650}
                  onChange={(value) => updateSetting("audit_log_retention_days", value)}
                />

                <div className="space-y-3 rounded-lg border border-slate-200 p-4">
                  <ToggleSetting
                    label="Require client email"
                    checked={settings.require_client_email}
                    onChange={(checked) => updateSetting("require_client_email", checked)}
                  />
                  <ToggleSetting
                    label="Require client phone"
                    checked={settings.require_client_phone}
                    onChange={(checked) => updateSetting("require_client_phone", checked)}
                  />
                  <ToggleSetting
                    label="Allow managers to create groups"
                    checked={settings.allow_manager_group_creation}
                    onChange={(checked) => updateSetting("allow_manager_group_creation", checked)}
                  />
                </div>
              </div>
            )}

            {saveError && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{saveError}</div>}
            {saveMessage && (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{saveMessage}</div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardContent className="space-y-5 p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600">
                <Trash2 className="h-5 w-5" />
              </span>
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold text-slate-900">Delete All Data</h2>
                  <Badge variant="secondary">Permanent</Badge>
                </div>
                <p className="max-w-3xl text-sm text-slate-600">
                  Deletes all groups, archived groups, passport uploads, extracted details, related processing jobs,
                  notifications, audit entries, stored passport images, and all WhatsApp broadcast data.
                </p>
              </div>
            </div>
          </div>

          {!canPurge ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
              Only super admins and agency admins can delete passport data.
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-end">
              <Input
                label={`Type ${DELETE_CONFIRMATION} to confirm`}
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                placeholder={DELETE_CONFIRMATION}
                disabled={isPurging}
              />
              <Button
                type="button"
                variant="danger"
                className="w-full lg:w-auto"
                disabled={!isConfirmed}
                isLoading={isPurging}
                leftIcon={<AlertTriangle className="h-4 w-4" />}
                onClick={() => setIsPurgeDialogOpen(true)}
              >
                Delete All Data
              </Button>
            </div>
          )}

          {purgeError && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{purgeError}</div>
          )}
          {purgeResult && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
              Deleted {purgeResult.deleted_client_groups} groups, {purgeResult.deleted_passport_submissions} passports,
              {purgeResult.deleted_processing_jobs} jobs, {purgeResult.deleted_notifications} notifications,
              {purgeResult.deleted_audit_logs} audit entries, {purgeResult.deleted_storage_objects} storage files,
              and {purgeResult.deleted_whatsapp_broadcast_groups} WhatsApp broadcasts with{" "}
              {purgeResult.deleted_whatsapp_recipients} recipients,{" "}
              {purgeResult.deleted_whatsapp_support_contacts} support contacts, and{" "}
              {purgeResult.deleted_whatsapp_message_logs} message records with{" "}
              {purgeResult.deleted_whatsapp_delivery_states} delivery checklists.
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        isOpen={isPurgeDialogOpen}
        title="Permanently Delete All Data"
        description="This will permanently delete all groups, archived groups, uploaded passport images, extracted passport details, related processing jobs, notifications, audit entries, and every WhatsApp broadcast, recipient, support contact, and message record. This action cannot be undone."
        confirmLabel="Delete All Data"
        variant="danger"
        isLoading={isPurging}
        onClose={() => setIsPurgeDialogOpen(false)}
        onConfirm={handlePurgePassportData}
      />
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

function SelectSetting({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-2 text-sm font-medium text-slate-700">
      <span>{label}</span>
      <select
        className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberSetting({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="space-y-2 text-sm font-medium text-slate-700">
      <span>{label}</span>
      <input
        className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function ToggleSetting({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center justify-between gap-4 text-sm font-medium text-slate-700">
      <span>{label}</span>
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}
