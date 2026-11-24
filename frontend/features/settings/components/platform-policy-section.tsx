import { Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { LockKeyhole, Save } from "lucide-react";
import type { PlatformSettings } from "../platform-settings-policy";
import type { PlatformSettingsController } from "../hooks/use-platform-settings";
import { SettingsSection, SelectSetting, NumberSetting, ToggleSetting } from "./platform-setting-controls";

export function PlatformPolicySection({ controller }: { controller: PlatformSettingsController }) {
  const { settings, loadState, loadError, isLoading, isSuperAdmin, canEditPolicies,
    isSaving, saveError, saveMessage, settingsStatusLabel, updateSetting,
    handleSave, reloadAuthoritativeSettings } = controller;
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-slate-500">{settingsStatusLabel}</p>
        <Button
          type="button"
          onClick={handleSave}
          isLoading={isSaving}
          disabled={!canEditPolicies}
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
              <p hidden={isSuperAdmin} className="text-sm text-slate-500">
                Only a super administrator can change these platform-wide policies.
              </p>
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
                disabled={!canEditPolicies || isSaving}
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
                    label="AI review threshold"
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
                    <p className="rounded-xl border border-blue-100 bg-blue-50 p-3 text-sm leading-6 text-blue-900">
                      Every traveller must provide an email and verify their WhatsApp number with an OTP before continuing to the submission details. This also applies to every family member.
                    </p>
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
  );
}
