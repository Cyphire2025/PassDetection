import { Badge, Button, Card, CardContent, ConfirmDialog, Input } from "@/components/ui";
import { AlertTriangle, Trash2 } from "lucide-react";
import type { PlatformSettingsController } from "../hooks/use-platform-settings";
import { DELETE_CONFIRMATION, type PlatformDataPurgeController } from "../hooks/use-platform-data-purge";

export function PlatformDataSection({ controller, purge }: {
  controller: PlatformSettingsController; purge: PlatformDataPurgeController;
}) {
  const { isAuthorityReady, loadState, canPurge, reloadAuthoritativeSettings } = controller;
  const { confirmation, setConfirmation, isConfirmed, isPurging, purgeError,
    purgeResult, isPurgeDialogOpen, setIsPurgeDialogOpen, handlePurgePassportData } = purge;
  return (
    <>
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
    </>
  );
}
