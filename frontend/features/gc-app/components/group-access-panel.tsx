"use client";

import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { Button, Card, CardContent, Input } from "@/components/ui";
import type { GcAppControlPatch, GcAppGroupControl } from "../types";
import { gcAppErrorMessage, toApiDateTime, toLocalDateTime } from "../utils";
import { AccessSwitch, GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

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
  const [startsAt, setStartsAt] = useState(() => toLocalDateTime(control.access_starts_at));
  const [expiresAt, setExpiresAt] = useState(() => toLocalDateTime(control.access_expires_at));
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = control.lifecycle === "archived" || control.lifecycle === "deleted" || Boolean(control.access_revoked_at);

  const update = async (patch: GcAppControlPatch) => {
    setError(null);
    try {
      await onUpdate(patch);
    } catch (updateError) {
      setError(gcAppErrorMessage(updateError, "Access settings were not changed. Refresh and try again."));
    }
  };

  const saveWindow = async () => {
    const start = toApiDateTime(startsAt);
    const expiry = toApiDateTime(expiresAt);
    if (start && expiry && new Date(expiry) <= new Date(start)) {
      setError("App-access expiry must be after the start date and time.");
      return;
    }
    await update({ access_starts_at: start, access_expires_at: expiry });
  };

  return (
    <div className="space-y-5">
      {error && <GcAlert message={error} />}
      {control.access_revoked_at && (
        <GcAlert message="Mobile access is currently revoked for every role in this group." />
      )}
      <Card>
        <CardContent className="space-y-4 p-5">
          <div>
            <h3 className="font-semibold text-slate-900">Role access</h3>
            <p className="mt-1 text-sm text-slate-500">Each role is enforced by the backend. Turning a switch off does not modify the underlying travel group.</p>
          </div>
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
            disabled={blocked || isUpdating}
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
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 p-5">
          <div>
            <h3 className="font-semibold text-slate-900">App-access window</h3>
            <p className="mt-1 text-sm text-slate-500">Times are entered in your local timezone and stored by the backend as UTC.</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Access starts" type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} disabled={blocked || isUpdating} />
            <Input label="Access expires" type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} disabled={blocked || isUpdating} />
          </div>
          <div className="flex flex-wrap justify-between gap-3">
            <Button type="button" variant="danger" onClick={() => setRevokeOpen(true)} disabled={Boolean(control.access_revoked_at) || isUpdating}>
              Immediately revoke access
            </Button>
            <Button type="button" onClick={() => void saveWindow()} isLoading={isUpdating} disabled={blocked}>
              Save access window
            </Button>
          </div>
        </CardContent>
      </Card>

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
