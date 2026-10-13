"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { useModalKeyboardBoundary } from "@/components/ui/modal";
import type { ReplacementRequest, ReturningHistory } from "../types";

export function ReturningUpdateDialog({ history, onClose, onContinue }: { history: ReturningHistory; onClose: () => void; onContinue: (request: ReplacementRequest) => void }) {
  const [kind, setKind] = useState<ReplacementRequest["changeKind"] | "">("");
  const title = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const keyboard = useModalKeyboardBoundary({ dialogRef, isOpen: true, canClose: true, onClose });
  return <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={title} onKeyDown={keyboard} className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"><form className="w-full max-w-md space-y-4 rounded-2xl bg-white p-5 shadow-xl" onSubmit={(event) => { event.preventDefault(); if (kind) onContinue({ reviewVersion: history.review_version, displayName: history.display_name, changeKind: kind }); }}>
    <h2 id={title} className="text-lg font-semibold text-slate-950">Update {history.display_name}’s passport</h2>
    <p className="text-sm leading-6 text-slate-600">Upload and review the current document for this person. Your travel team will check the update before it can replace the accepted passport for future trips. Previous trip records stay preserved.</p>
    <fieldset className="space-y-3"><legend className="mb-2 text-sm font-medium text-slate-700">What changed?</legend>{([{ value: "renewal", label: "A renewed or replacement passport" }, { value: "scan", label: "A clearer scan of the same passport" }, { value: "correction", label: "A correction to the saved passport details" }] as const).map((option) => <label key={option.value} className="flex items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm leading-6"><input type="radio" name="passport-update-kind" required checked={kind === option.value} onChange={() => setKind(option.value)} className="mt-1" /><span>{option.label}</span></label>)}</fieldset>
    <p className="text-xs leading-5 text-slate-500">Keep this tab open while uploading. If verification expires or the page reloads, the document can still be submitted and your organiser can review its association.</p>
    <div className="flex flex-col gap-2 sm:flex-row sm:justify-end"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" className="h-auto min-h-11 whitespace-normal" disabled={!kind}>Continue to updated document</Button></div>
  </form></div>;
}
