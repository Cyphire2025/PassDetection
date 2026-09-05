"use client";

import {
  Badge,
  Button,
  Card,
  CardContent,
  ConfirmDialog,
  Input,
  Skeleton,
} from "@/components/ui";
import {
  buildPlatformSettingsUpdate,
  conflictCurrentUpdatedAt,
  DEFAULT_PLATFORM_SETTINGS,
  isPlatformSettingsRevisionConflict,
  type PlatformSettings,
} from "@/features/settings/platform-settings-policy";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { formatDateTime } from "@/lib/utils/format";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { AlertTriangle, LockKeyhole, Save, Trash2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

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

const DELETE_CONFIRMATION = "DELETE ALL DATA";
type SettingsLoadState = "loading" | "ready" | "error" | "conflict";

export function PlatformSettingsPanel({
  section,
}: {
  section: "policies" | "data";
}) {
  const user = useAuthStore(selectUser);
  const [settings, setSettings] = useState<PlatformSettings>(
    DEFAULT_PLATFORM_SETTINGS,
  );
  const [authoritativeUpdatedAt, setAuthoritativeUpdatedAt] = useState<
    string | null
  >(null);
  const [loadState, setLoadState] = useState<SettingsLoadState>("loading");
  const [loadRequest, setLoadRequest] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [isPurging, setIsPurging] = useState(false);
  const [purgeError, setPurgeError] = useState<string | null>(null);
  const [purgeResult, setPurgeResult] =
    useState<PurgePassportDataResponse | null>(null);
  const [isPurgeDialogOpen, setIsPurgeDialogOpen] = useState(false);

  const isLoading = loadState === "loading";
  const isAuthorityReady = loadState === "ready" && user !== null;
  const canPurge =
    isAuthorityReady &&
    (user.role === "super_admin" || user.role === "agency_admin");
  const isConfirmed = confirmation === DELETE_CONFIRMATION;

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    apiClient
      .get<PlatformSettings>(API_ENDPOINTS.admin.settings, {
        signal: controller.signal,
      })
      .then(({ data }) => {
        if (!active) return;
        setSettings(data);
        setAuthoritativeUpdatedAt(data.updated_at);
        setLoadState("ready");
      })
      .catch(() => {
        if (!active) return;
        setLoadError(
          "Could not load authoritative platform settings. Editing and destructive actions remain unavailable until the server state is loaded.",
        );
        setLoadState("error");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [loadRequest]);

  const updateSetting = <K extends keyof PlatformSettings>(
    key: K,
    value: PlatformSettings[K],
  ) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  const handleSave = async () => {
    if (loadState !== "ready" || isSaving) return;
    setIsSaving(true);
    setSaveError(null);
    setSaveMessage(null);
    try {
      const payload = buildPlatformSettingsUpdate(
        settings,
        authoritativeUpdatedAt,
      );
      const { data } = await apiClient.put<PlatformSettings>(
        API_ENDPOINTS.admin.settings,
        payload,
      );
      setSettings(data);
      setAuthoritativeUpdatedAt(data.updated_at);
      setSaveMessage("Settings saved.");
    } catch (error) {
      if (isPlatformSettingsRevisionConflict(error)) {
        const currentUpdatedAt = conflictCurrentUpdatedAt(error);
        const revisionMessage = currentUpdatedAt
          ? ` The server reports a newer revision saved ${formatDateTime(currentUpdatedAt)}.`
          : " The server state no longer matches the version that was loaded.";
        setLoadState("conflict");
        setSaveError(
          `Platform settings changed before this save completed.${revisionMessage} Your edits are preserved here; reload the authoritative settings before editing or saving again.`,
        );
      } else {
        setSaveError(
          "Could not save settings. Your edits are still present and were not reported as saved.",
        );
      }
    } finally {
      setIsSaving(false);
    }
  };

  const reloadAuthoritativeSettings = () => {
    if (
      loadState === "conflict" &&
      !window.confirm(
        "Reload the authoritative platform settings? This replaces the unsaved edits currently shown on this page.",
      )
    ) {
      return;
    }
    setLoadState("loading");
    setLoadError(null);
    setSaveError(null);
    setSaveMessage(null);
    setLoadRequest((current) => current + 1);
  };

  const settingsStatusLabel =
    loadState === "loading"
      ? "Loading saved policy"
      : loadState === "error"
        ? "Settings unavailable"
        : loadState === "conflict"
          ? "Reload required"
          : settings.updated_at
            ? `Saved ${formatDateTime(settings.updated_at)}`
            : "No saved policy yet";

  const handlePurgePassportData = async () => {
    if (!isAuthorityReady || !canPurge || !isConfirmed || isPurging) return;

    setIsPurging(true);
    setPurgeError(null);
    setPurgeResult(null);
    try {
      const { data } = await apiClient.delete<PurgePassportDataResponse>(
        API_ENDPOINTS.admin.passportData,
      );
      setPurgeResult(data);
      setConfirmation("");
      setIsPurgeDialogOpen(false);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Could not delete passport data.";
      setPurgeError(message);
    } finally {
      setIsPurging(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {section === "policies" && (
        <>
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-slate-500">{settingsStatusLabel}</p>
            <Button
              type="button"
              onClick={handleSave}
              isLoading={isSaving}
              disabled={loadState !== "ready"}
              leftIcon={<Save className="h-4 w-4" />}
            >
              Save policies
            </Button>
          </div>
          <Card>
            <CardContent className="space-y-6 p-5">
              <div className="flex flex-col gap-3 border-b border-slate-100 pb-5 lg:flex-row lg:items-start lg:justify-between">
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-100 text-slate-600">
                    <LockKeyhole className="h-5 w-5" />
                  </span>
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">
                      Platform Controls
                    </h2>
                    <p className="text-sm text-slate-500">
                      {settingsStatusLabel}
                    </p>
                  </div>
                </div>
              </div>

              {isLoading ? (
                <div className="grid gap-4 md:grid-cols-2">
                  <Skeleton className="h-24 w-full rounded-lg" />
                  <Skeleton className="h-24 w-full rounded-lg" />
                  <Skeleton className="h-24 w-full rounded-lg" />
                  <Skeleton className="h-24 w-full rounded-lg" />
                </div>
              ) : loadState === "error" ? (
                <div
                  role="alert"
                  className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
                >
                  <p>{loadError}</p>
                  <Button
                    type="button"
                    variant="secondary"
                    className="mt-3"
                    onClick={reloadAuthoritativeSettings}
                  >
                    Retry loading settings
                  </Button>
                </div>
              ) : (
                <div className="space-y-6">
                  {loadState === "conflict" && (
                    <div
                      role="alert"
                      className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950"
                    >
                      <p>{saveError}</p>
                      <Button
                        type="button"
                        variant="secondary"
                        className="mt-3"
                        onClick={reloadAuthoritativeSettings}
                      >
                        Reload current settings
                      </Button>
                    </div>
                  )}
                  <fieldset
                    disabled={loadState !== "ready" || isSaving}
                    className="space-y-6 disabled:opacity-75"
                  >
                    <SettingsSection
                      title="Identity and intake defaults"
                      description="Set defaults for new groups and duplicate contact details."
                    >
                      <Input
                        label="Platform name"
                        value={settings.platform_name}
                        onChange={(event) =>
                          updateSetting("platform_name", event.target.value)
                        }
                      />

                      <SelectSetting
                        label="Default new group status"
                        value={settings.default_group_status}
                        onChange={(value) =>
                          updateSetting(
                            "default_group_status",
                            value as PlatformSettings["default_group_status"],
                          )
                        }
                        options={[
                          ["active", "Active"],
                          ["closed", "Closed"],
                        ]}
                      />

                      <SelectSetting
                        label="Duplicate client contact policy"
                        value={settings.duplicate_contact_policy}
                        onChange={(value) =>
                          updateSetting(
                            "duplicate_contact_policy",
                            value as PlatformSettings["duplicate_contact_policy"],
                          )
                        }
                        options={[
                          [
                            "block_same_group",
                            "Block duplicates in same group",
                          ],
                          ["block_all", "Block duplicates across platform"],
                          ["allow", "Allow duplicates"],
                        ]}
                      />
                    </SettingsSection>

                    <SettingsSection
                      title="Review and retention"
                      description="Set the manual review threshold and data retention periods."
                    >
                      <NumberSetting
                        label="MRZ review threshold"
                        value={settings.mrz_review_threshold}
                        min={0}
                        max={1}
                        step={0.01}
                        onChange={(value) =>
                          updateSetting("mrz_review_threshold", value)
                        }
                      />

                      <NumberSetting
                        label="Auto-archive closed groups after days"
                        value={settings.auto_archive_closed_groups_days}
                        min={1}
                        max={3650}
                        onChange={(value) =>
                          updateSetting(
                            "auto_archive_closed_groups_days",
                            value,
                          )
                        }
                      />

                      <NumberSetting
                        label="Passport data retention days"
                        value={settings.passport_data_retention_days}
                        min={1}
                        max={3650}
                        onChange={(value) =>
                          updateSetting("passport_data_retention_days", value)
                        }
                      />

                      <NumberSetting
                        label="Audit log retention days"
                        value={settings.audit_log_retention_days}
                        min={1}
                        max={3650}
                        onChange={(value) =>
                          updateSetting("audit_log_retention_days", value)
                        }
                      />
                    </SettingsSection>

                    <fieldset className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
                      <legend className="px-1 text-sm font-semibold text-slate-950">
                        Access requirements
                      </legend>
                      <p className="mb-4 mt-1 text-sm leading-6 text-slate-600">
                        Control required client contact fields and manager-level
                        group creation.
                      </p>
                      <div className="grid gap-2">
                        <ToggleSetting
                          label="Require client email"
                          checked={settings.require_client_email}
                          onChange={(checked) =>
                            updateSetting("require_client_email", checked)
                          }
                        />
                        <ToggleSetting
                          label="Require client phone"
                          checked={settings.require_client_phone}
                          onChange={(checked) =>
                            updateSetting("require_client_phone", checked)
                          }
                        />
                        <ToggleSetting
                          label="Allow managers to create groups"
                          checked={settings.allow_manager_group_creation}
                          onChange={(checked) =>
                            updateSetting(
                              "allow_manager_group_creation",
                              checked,
                            )
                          }
                        />
                      </div>
                    </fieldset>
                  </fieldset>
                </div>
              )}

              {saveError && loadState !== "conflict" && (
                <div
                  role="alert"
                  className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
                >
                  {saveError}
                </div>
              )}
              {saveMessage && (
                <div
                  role="status"
                  className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
                >
                  {saveMessage}
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {section === "data" && (
        <Card className="overflow-hidden border-red-200">
          <CardContent className="space-y-5 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-50 text-red-600">
                  <Trash2 className="h-5 w-5" />
                </span>
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold text-slate-900">
                      Delete All Data
                    </h2>
                    <Badge variant="secondary">Permanent</Badge>
                  </div>
                  <p className="max-w-3xl text-sm text-slate-600">
                    Deletes all groups, archived groups, passport uploads,
                    extracted details, related processing jobs, notifications,
                    stored passport images, and all WhatsApp broadcast data.
                    Append-only audit evidence is retained so the administrative
                    action remains accountable.
                  </p>
                </div>
              </div>
            </div>

            {!isAuthorityReady ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                This action is unavailable until your permissions
                and current settings have loaded.
                {loadState === "error" && (
                  <Button
                    type="button"
                    variant="secondary"
                    className="mt-3"
                    onClick={reloadAuthoritativeSettings}
                  >
                    Retry loading settings
                  </Button>
                )}
              </div>
            ) : !canPurge ? (
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
                  disabled={!isAuthorityReady || isPurging}
                />
                <Button
                  type="button"
                  variant="danger"
                  className="w-full lg:w-auto"
                  disabled={!isAuthorityReady || !isConfirmed}
                  isLoading={isPurging}
                  leftIcon={<AlertTriangle className="h-4 w-4" />}
                  onClick={() => setIsPurgeDialogOpen(true)}
                >
                  Delete All Data
                </Button>
              </div>
            )}

            {purgeError && (
              <div
                role="alert"
                className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
              >
                {purgeError}
              </div>
            )}
            {purgeResult && (
              <div
                role="status"
                className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800"
              >
                Deleted {purgeResult.deleted_client_groups} groups,{" "}
                {purgeResult.deleted_passport_submissions} passports,
                {purgeResult.deleted_processing_jobs} jobs,{" "}
                {purgeResult.deleted_notifications} notifications,
                {purgeResult.deleted_storage_objects} storage files, and{" "}
                {purgeResult.deleted_whatsapp_broadcast_groups} WhatsApp
                broadcasts with {purgeResult.deleted_whatsapp_recipients}{" "}
                recipients, {purgeResult.deleted_whatsapp_support_contacts}{" "}
                support contacts, and{" "}
                {purgeResult.deleted_whatsapp_message_logs} message records with{" "}
                {purgeResult.deleted_whatsapp_delivery_states} delivery
                checklists. Append-only audit evidence was retained.
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        isOpen={isPurgeDialogOpen && isAuthorityReady}
        title="Permanently Delete All Data"
        description="This will permanently delete all groups, archived groups, uploaded passport images, extracted passport details, related processing jobs, notifications, and every WhatsApp broadcast, recipient, support contact, and message record. Append-only audit evidence is retained. The operational-data deletion cannot be undone."
        confirmLabel="Delete All Data"
        variant="danger"
        isLoading={isPurging}
        onClose={() => setIsPurgeDialogOpen(false)}
        onConfirm={handlePurgePassportData}
      />
    </div>
  );
}

function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section
      className="rounded-xl border border-slate-200 p-4"
      aria-label={title}
    >
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
        <p className="mt-1 text-sm leading-6 text-slate-600">{description}</p>
      </div>
      <div className="grid gap-5 md:grid-cols-2">{children}</div>
    </section>
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
    <label className="flex min-h-11 cursor-pointer items-center justify-between gap-4 rounded-lg border border-transparent bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:border-slate-200">
      <span>{label}</span>
      <span className="relative shrink-0">
        <input
          type="checkbox"
          className="peer sr-only"
          checked={checked}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span
          className="block h-6 w-11 rounded-full bg-slate-300 transition-colors peer-checked:bg-blue-600 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-600 peer-focus-visible:ring-offset-2 after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-5"
          aria-hidden="true"
        />
      </span>
    </label>
  );
}
