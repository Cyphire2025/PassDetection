"use client";
import type { Dispatch, SetStateAction } from "react";
import { CheckCircle2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandLogo } from "@/components/brand/brand-logo";
import type { useReturningDraft } from "../hooks/use-returning-draft";
import type { ReturningHistory } from "../types";
type DraftForm = ReturnType<typeof useReturningDraft>;
type Props = {
  history: ReturningHistory;
  groupName: string;
  form: DraftForm;
  draft: DraftForm["draft"];
  loading: boolean;
  loadError?: string;
  reload: (id?: string) => Promise<void>;
  replacement: boolean;
  setReplacement: Dispatch<SetStateAction<boolean>>
};

export function ReturningReviewHeader({ history, groupName, form, draft, loading, loadError, reload, replacement, setReplacement }: Props) {
  return (<>
    <BrandLogo className="mx-auto mb-6 h-12 w-[190px] sm:mb-8 sm:h-14 sm:w-[210px]" priority />
    <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="max-w-2xl">
        <p className="text-sm font-medium text-blue-700">
          {groupName}
        </p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">Ready for your next journey</h1>
        <p className="mt-3 text-sm leading-6 text-slate-500">Review your passport and complete this trip’s details. If your passport hasn’t changed, you don’t need to upload it again.</p>
      </div>
      <span
        className="inline-flex w-fit shrink-0 items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-medium text-emerald-800"
      >
        <CheckCircle2 className="h-4 w-4" />Passport verified</span>
    </header>
    {(history.available_passports?.length ?? 0) > 1 && <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-4">
      <label htmlFor="trip-passport" className="text-sm font-medium text-slate-700">Passport for this trip</label>
      <select
        id="trip-passport"
        value={history.passport?.id ?? ""}
        disabled={form.pending || loading}
        onChange={(event) => {
          const id = event.target.value;
          void form.flush().then(() => reload(id)).catch(() => undefined);
        }}
        className="mt-2 min-h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-base"
      >
        {history.available_passports?.map((passport) => <option key={passport.id} value={passport.id}>
          {passport.number}
          {passport.is_default ? " · Usual passport" : ""}
        </option>)}
      </select>
    </section>}
    {loadError && <p role="alert" className="mb-4 rounded-xl bg-red-50 p-4 text-sm text-red-800">
      {loadError}
    </p>}
    <div
      className="mb-6 flex flex-col gap-4 rounded-2xl border border-blue-100 bg-white/95 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"
    >
      <div>
        <p className="font-medium text-slate-900">Has your passport changed?</p>
        <p className="mt-1 text-sm leading-6 text-slate-500">Upload new pages only for a renewed passport, corrected document, or clearer copy.</p>
      </div>
      <Button
        type="button"
        variant="secondary"
        className="h-auto min-h-12 shrink-0 whitespace-normal"
        disabled={!draft || form.pending}
        aria-expanded={replacement}
        onClick={() => setReplacement(true)}
      >
        <Upload className="h-4 w-4" />Update Documents</Button>
    </div>
    {form.error && <div
      role="alert"
      className="mb-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-6 text-red-800"
    >
      {form.error}
      <button type="button" onClick={form.retry} className="ml-3 min-h-10 font-semibold underline">Retry</button>
      <button
        type="button"
        disabled={loading}
        onClick={() => void reload()}
        className="ml-3 min-h-10 font-semibold underline"
      >Refresh current trip requirements</button>
    </div>}
  </>);
}
