"use client";

import { useState } from "react";
import { Button, Card, CardContent, Input } from "@/components/ui";
import type { GcAppControlPatch, GcAppGroupControl } from "../types";
import { gcAppErrorMessage, toApiDateTime, toLocalDateTime } from "../utils";
import { GcAlert } from "./gc-app-feedback";

interface WindowDraft {
  starts: string;
  expires: string;
  savedStarts: string | null;
  savedExpires: string | null;
}

export function GroupAccessWindow({ control, disabled, onUpdate }: {
  control: GcAppGroupControl;
  disabled: boolean;
  onUpdate: (patch: GcAppControlPatch) => Promise<void>;
}) {
  const [draft, setDraft] = useState<WindowDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const current = draft ?? {
    starts: toLocalDateTime(control.access_starts_at),
    expires: toLocalDateTime(control.access_expires_at),
    savedStarts: control.access_starts_at,
    savedExpires: control.access_expires_at,
  };
  const changedElsewhere = draft !== null && (
    draft.savedStarts !== control.access_starts_at || draft.savedExpires !== control.access_expires_at
  );
  const edit = (field: "starts" | "expires", value: string) => {
    setSaved(false);
    setDraft({ ...current, [field]: value });
  };
  const save = async () => {
    if (disabled || changedElsewhere) return;
    setError(null);
    const start = toApiDateTime(current.starts);
    const expiry = toApiDateTime(current.expires);
    if ((current.starts && !start) || (current.expires && !expiry)) {
      setError("Enter a valid local date and time, or leave the field empty.");
      return;
    }
    if (start && expiry && new Date(expiry) <= new Date(start)) {
      setError("App-access expiry must be after the start date and time.");
      return;
    }
    try {
      await onUpdate({ access_starts_at: start, access_expires_at: expiry });
      setDraft(null);
      setSaved(true);
    } catch (saveError) {
      setError(gcAppErrorMessage(saveError, "Access dates were not saved. Review the latest settings and try again."));
    }
  };

  return (
    <Card><CardContent className="space-y-4 p-5">
      <div><h3 className="font-semibold text-slate-900">When can users access this trip?</h3>
        <p className="mt-1 text-sm text-slate-500">Dates use your local timezone. Leave the start empty for immediate access and the expiry empty for no end date. These dates also apply to common documents.</p>
      </div>
      {error && <GcAlert message={error} />}
      {saved && <GcAlert tone="success" message="App-access dates saved." />}
      {changedElsewhere && <GcAlert message="The saved access dates changed while you were editing. Your draft is kept below. Load the latest saved dates before making another change." />}
      <div className="grid gap-4 md:grid-cols-2">
        <Input label="Access starts" type="datetime-local" value={current.starts} onChange={(event) => edit("starts", event.target.value)} disabled={disabled} />
        <Input label="Access expires" type="datetime-local" value={current.expires} onChange={(event) => edit("expires", event.target.value)} disabled={disabled} />
      </div>
      <p className="text-xs text-slate-500">Changing these dates ends existing trip sessions. Users can sign in again within the new access window.</p>
      <div className="flex flex-wrap items-center justify-end gap-3">
        {draft && <Button type="button" variant="secondary" disabled={disabled} onClick={() => { setDraft(null); setError(null); }}>
          {changedElsewhere ? "Load latest saved dates" : "Discard date edits"}
        </Button>}
        <Button type="button" disabled={disabled || !draft || changedElsewhere} onClick={() => void save()}>Save access window</Button>
      </div>
    </CardContent></Card>
  );
}
