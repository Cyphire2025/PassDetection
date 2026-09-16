"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { describeAppAvailability } from "../availability";
import { useGcAppGroupMutations } from "../hooks/use-gc-app-admin";
import type { GcAppGroupControl } from "../types";
import { gcAppErrorMessage } from "../utils";
import { GcAlert } from "./gc-app-feedback";
import { GcDialog } from "./gc-dialog";

export function RemoveAppGroupDialog({ agencyId, group, onClose, onRemoved }: {
  agencyId: string;
  group: GcAppGroupControl;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const [current, setCurrent] = useState(group);
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [needsReload, setNeedsReload] = useState(false);
  const [reloading, setReloading] = useState(false);
  const active = useRef(true);
  const busy = useRef(false);
  const reloadController = useRef<AbortController | null>(null);
  const { remove } = useGcAppGroupMutations(agencyId);
  const pending = remove.isPending || reloading;

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      reloadController.current?.abort();
    };
  }, []);

  const submit = async () => {
    if (busy.current || needsReload || confirmation !== current.name) return;
    busy.current = true;
    setError(null);
    try {
      await remove.mutateAsync(current);
      if (active.current) onRemoved();
    } catch (failure) {
      if (!active.current) return;
      setError(gcAppErrorMessage(failure, "The removal could not be confirmed. Reload the trip before trying again."));
      setNeedsReload(true);
      setConfirmation("");
    } finally {
      busy.current = false;
    }
  };

  const reload = async () => {
    if (busy.current) return;
    busy.current = true;
    setReloading(true);
    setError(null);
    const controller = new AbortController();
    reloadController.current = controller;
    try {
      const updated = await gcAppAdminApi.getGroupControl(agencyId, group.id, controller.signal);
      if (!active.current) return;
      if (updated.gc_removed_at) {
        onRemoved();
        return;
      }
      setCurrent(updated);
      setConfirmation("");
      setNeedsReload(false);
    } catch (failure) {
      if (active.current) setError(gcAppErrorMessage(failure, "Current trip details could not be loaded. Please retry."));
    } finally {
      busy.current = false;
      if (active.current) setReloading(false);
    }
  };

  return (
    <GcDialog
      open
      title="Remove group from GC App?"
      description={current.name}
      size="md"
      onClose={() => { if (!busy.current) onClose(); }}
      closeDisabled={pending}
      footer={<>
        <Button type="button" variant="secondary" disabled={pending} onClick={() => { if (!busy.current) onClose(); }}>Cancel</Button>
        <Button type="button" variant="danger" isLoading={remove.isPending}
          disabled={pending || needsReload || confirmation !== current.name} onClick={() => void submit()}>
          Remove from GC App
        </Button>
      </>}
    >
      <div className="space-y-4">
        <div className="flex gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <div className="space-y-2">
            <p>This trip will become unavailable in GC App and disappear from App Controls.</p>
            <p>The original passport group, travellers, documents and history will be kept.</p>
            <p>You can add it again if the original group is open or closed. Archived groups must be restored first.</p>
          </div>
        </div>
        <p className="text-sm text-slate-600">Current app status: <strong>{describeAppAvailability(current).label}</strong> · {current.active_mobile_users} active mobile users</p>
        {error && <GcAlert message={error} />}
        {needsReload ? (
          <div className="space-y-2">
            <p className="text-sm text-slate-600">Reload the current details and review them before confirming again.</p>
            <Button type="button" variant="secondary" isLoading={reloading} onClick={() => void reload()}>Reload trip details</Button>
          </div>
        ) : (
          <Input label={`Type ${current.name} to confirm`} value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)} disabled={pending}
            autoComplete="off" placeholder={current.name} />
        )}
      </div>
    </GcDialog>
  );
}
