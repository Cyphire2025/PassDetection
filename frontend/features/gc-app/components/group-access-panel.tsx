"use client";

import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { describeAppAvailability } from "../availability";
import type { GcAppControlPatch, GcAppGroupControl } from "../types";
import { gcAppErrorMessage } from "../utils";
import { AccessSwitch, GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";
import { GroupAccessWindow } from "./group-access-window";

export function GroupAccessPanel({
  control,
  isUpdating,
  onUpdate,
  onSetMyPhotosEnabled,
  onRevoke,
}: {
  control: GcAppGroupControl;
  isUpdating: boolean;
  onUpdate: (patch: GcAppControlPatch) => Promise<void>;
  onSetMyPhotosEnabled: (enabled: boolean) => Promise<void>;
  onRevoke: () => Promise<void>;
}) {
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = control.lifecycle === "archived" || control.lifecycle === "deleted";
  const enabled = control.gc_app_enabled && !control.access_revoked_at;
  const availability = describeAppAvailability(control);
  const photosPrerequisite = blocked || !enabled || !control.passenger_access_enabled;

  const update = async (patch: GcAppControlPatch) => {
    setError(null);
    try {
      await onUpdate(patch);
    } catch (updateError) {
      setError(gcAppErrorMessage(updateError, "Access settings were not changed. Refresh and try again."));
    }
  };

  return (
    <div className="space-y-5">
      {error && <GcAlert message={error} />}
      <Card><CardContent className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="font-semibold text-slate-900">App availability</h3>
          <Badge variant={availability.variant}>{availability.label}</Badge>
        </div>
        <p className="text-sm text-slate-600">{availability.description}</p>
        <p className="text-sm text-slate-500">GC App access is independent of the passport collection link. Pausing keeps the trip, role permissions, dates, and published content available for staff to manage.</p>
        <Button type="button" variant={enabled ? "secondary" : "primary"} disabled={blocked || isUpdating} onClick={() => void update({ enabled: !enabled })}>
          {enabled ? "Pause app access" : control.access_revoked_at ? "Restore app access" : "Enable app access"}
        </Button>
        {blocked ? <p className="text-xs text-slate-500">Access settings are unavailable for archived or deleted passport groups.</p>
          : <p className="text-xs text-slate-500">Pausing ends existing trip sessions. Restoring respects the saved access window and role permissions; it does not sign users in automatically.</p>}
      </CardContent></Card>
      <Card>
        <CardContent className="space-y-4 p-5">
          <div>
            <h3 className="font-semibold text-slate-900">Who can access this trip?</h3>
            <p className="mt-1 text-sm text-slate-500">Choose allowed roles. Passengers still need an eligible submitted record; Client Managers and Coordinators need their assigned accounts. Role permissions apply within the app-access window.</p>
          </div>
          {!enabled && <p className="text-xs text-slate-500">You can prepare role permissions while access is paused. Enable app access when ready.</p>}
          <div className="grid gap-3 md:grid-cols-3">
            <AccessSwitch label="Passenger access" checked={control.passenger_access_enabled} disabled={blocked || isUpdating} onChange={(enabled) => void update({ passenger_access_enabled: enabled })} />
            <AccessSwitch label="Client Manager access" checked={control.client_manager_access_enabled} disabled={blocked || isUpdating} onChange={(enabled) => void update({ client_manager_access_enabled: enabled })} />
            <AccessSwitch label="Coordinator access" checked={control.coordinator_access_enabled} disabled={blocked || isUpdating} onChange={(enabled) => void update({ coordinator_access_enabled: enabled })} />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 p-5">
          <div>
            <h3 className="font-semibold text-slate-900">Passenger features</h3>
            <p className="mt-1 text-sm text-slate-500">
              Optional trip features appear only for passengers who already have GC App access.
            </p>
          </div>
          <AccessSwitch
            label="My Photos"
            checked={control.my_photos_enabled}
            disabled={isUpdating || (!control.my_photos_enabled && photosPrerequisite)}
            onChange={(enabled) => {
              setError(null);
              void onSetMyPhotosEnabled(enabled).catch((updateError: unknown) => {
                setError(gcAppErrorMessage(
                  updateError,
                  "My Photos visibility was not changed. Refresh and try again.",
                ));
              });
            }}
          />
          <p className="text-xs text-slate-500">
            Show My Photos in the passenger app for this group. Gallery and provider setup are still required before photos can be used.
          </p>
          {photosPrerequisite && <p className="text-sm text-amber-800">Enable GC App and Passenger access for an available passport group before turning on My Photos. You can still turn off an existing feature.</p>}
        </CardContent>
      </Card>

      <GroupAccessWindow key={control.id} control={control} disabled={blocked || isUpdating} onUpdate={onUpdate} />

      <details className="rounded-xl border border-amber-200 bg-amber-50 p-5">
        <summary className="cursor-pointer text-sm font-semibold text-amber-950">Emergency access revocation</summary>
        <p className="my-3 text-sm text-amber-900">Revoke current trip access and instruct devices to clear its scoped offline data. Use Pause app access for routine changes.</p>
        <Button type="button" variant="danger" onClick={() => setRevokeOpen(true)} disabled={Boolean(control.access_revoked_at) || isUpdating}>
          Immediately revoke access
        </Button>
      </details>

      <GcDialog
        open={revokeOpen}
        title="Immediately revoke mobile access"
        description={`All mobile roles assigned to ${control.name} will be denied by the backend.`}
        onClose={() => !isUpdating && setRevokeOpen(false)}
        closeDisabled={isUpdating}
        size="md"
        footer={(
          <>
            <Button type="button" variant="secondary" onClick={() => setRevokeOpen(false)} disabled={isUpdating}>Cancel</Button>
            <Button
              type="button"
              variant="danger"
              isLoading={isUpdating}
              onClick={() => {
                setError(null);
                void onRevoke().then(() => setRevokeOpen(false)).catch((revokeError: unknown) => {
                  setError(gcAppErrorMessage(revokeError, "Access could not be revoked."));
                });
              }}
            >
              Revoke access now
            </Button>
          </>
        )}
      >
        <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <p>Devices will be instructed to clear this group’s scoped offline data. This does not close, archive, delete, or revoke the passport collection group.</p>
        </div>
      </GcDialog>
    </div>
  );
}
