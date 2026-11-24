"use client";

import { Clock3, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { aiSettingsApi, type UsageLimits } from "../settings-api";

const FIELDS = [
  { key: "daily_voice_chats", used: "voice_chats", label: "Voice chats per day", max: 10000, hint: "A chat counts once each day. Microphone reconnects in that chat do not add to it." },
  { key: "daily_requests", used: "typed_requests", label: "Typed requests per day", max: 10000, hint: "Text and image prompts from the composer, including typed input during a voice chat." },
  { key: "daily_images", used: "images", label: "Images per day", max: 500, hint: "Each generated image uses one unit." },
  { key: "daily_uploads", used: "uploads", label: "File uploads per day", max: 2000, hint: "Each uploaded attachment uses one unit." },
  { key: "daily_speech_requests", used: "speech_requests", label: "Speech requests per day", max: 10000, hint: "Standalone transcription and read-aloud requests. Native voice uses the voice-chat allowance." },
] as const;

export function validUsageLimits(value?: UsageLimits) {
  return !value || FIELDS.every(({ key, max }) => Number.isInteger(value[key]) && value[key] >= 0 && value[key] <= max)
    && Number.isInteger(value.voice_connection_minutes) && value.voice_connection_minutes >= 1 && value.voice_connection_minutes <= 60;
}

export function AssistantUsageSettings({ value, onChange, revision }: { value: UsageLimits; onChange: (value: UsageLimits) => void; revision: number }) {
  const user = useAuthStore(selectUser);
  const { data: usage, isError: error, isFetching: loading, refetch: load } = useQuery({
    queryKey: ["assistant-usage", user?.id, revision],
    queryFn: async ({ signal }) => {
      const next = await aiSettingsApi.usage(signal);
      if (!next.used || !next.resets_at) throw new Error("Usage unavailable");
      return next;
    },
    enabled: user?.role === "super_admin", staleTime: 0, gcTime: 0,
    refetchInterval: 30000, refetchOnWindowFocus: true, retry: 1,
  });
  const reset = usage ? new Date(usage.resets_at) : null;
  return <section aria-labelledby="assistant-usage-title" className="rounded-xl border border-slate-200 bg-white p-6">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 id="assistant-usage-title" className="text-sm font-semibold text-slate-900">Usage limits</h3><p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">Set the daily allowance for each authorized account. Current usage below is for your account. Set a daily allowance to 0 to disable that feature.</p></div><button type="button" disabled={loading} onClick={() => void load()} aria-label="Refresh current AI usage" className="rounded-lg border border-slate-200 p-2.5 text-slate-600 disabled:opacity-40"><RefreshCw size={16} className={loading ? "animate-spin" : ""} /></button></div>
    <div className="mt-5 grid gap-5 md:grid-cols-2">{FIELDS.map(({ key, used, label, max, hint }) => {
      const count = usage?.used[used] ?? 0, applied = usage?.limits[key] ?? (Number.isFinite(value[key]) ? value[key] : 0);
      return <div key={key} className="rounded-lg border border-slate-200 p-4"><div className="flex items-center justify-between gap-3"><label htmlFor={`ai-limit-${key}`} className="text-sm font-medium text-slate-700">{label}</label><input id={`ai-limit-${key}`} type="number" inputMode="numeric" min={0} max={max} step={1} value={Number.isNaN(value[key]) ? "" : value[key]} aria-describedby={`ai-limit-help-${key}`} aria-invalid={!Number.isInteger(value[key]) || value[key] < 0 || value[key] > max} onChange={(event) => onChange({ ...value, [key]: event.target.valueAsNumber })} className="w-24 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-blue-500" /></div><p id={`ai-limit-help-${key}`} className="mt-2 text-xs leading-5 text-slate-500">{hint} <span className="whitespace-nowrap">Range: 0–{max.toLocaleString()}.</span></p><div className="mt-3 flex justify-between text-xs text-slate-500"><span>Used today</span><span className="tabular-nums" data-testid={`usage-${used}`}>{usage ? `${count} / ${applied}${applied === 0 ? " · Disabled" : ""}` : "—"}</span></div><div role="progressbar" aria-label={`${label}: used today`} aria-valuemin={0} aria-valuemax={Math.max(1, applied)} aria-valuenow={usage ? Math.min(count, Math.max(1, applied)) : undefined} aria-valuetext={usage ? `${count} of ${applied}` : "Usage unavailable"} className="mt-2 h-1 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full transition-[width] ${count >= applied && applied > 0 ? "bg-amber-500" : "bg-blue-500"}`} style={{ width: `${Math.min(100, count / Math.max(1, applied) * 100)}%` }} /></div></div>;
    })}<div className="rounded-lg border border-slate-200 p-4"><label htmlFor="ai-voice-minutes" className="text-sm font-medium text-slate-700">Maximum voice connection (minutes)</label><input id="ai-voice-minutes" type="number" inputMode="numeric" min={1} max={60} step={1} value={Number.isNaN(value.voice_connection_minutes) ? "" : value.voice_connection_minutes} aria-invalid={!Number.isInteger(value.voice_connection_minutes) || value.voice_connection_minutes < 1 || value.voice_connection_minutes > 60} onChange={(event) => onChange({ ...value, voice_connection_minutes: event.target.valueAsNumber })} className="mt-3 block w-24 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-blue-500" /><p className="mt-2 text-xs leading-5 text-slate-500">1–60 minutes per continuous connection. Reconnect in the same chat to continue without using another daily voice chat.</p></div></div>
    {!validUsageLimits(value) ? <p role="alert" className="mt-4 text-sm text-rose-700">Use whole numbers within the displayed ranges. Voice connections must last 1–60 minutes.</p> : null}
    <div className="mt-5 rounded-lg bg-slate-50 p-3 text-xs leading-6 text-slate-600">{reset ? <p className="flex items-center gap-2"><Clock3 size={15} /><span>Daily reset: <time dateTime={usage!.resets_at}>{reset.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" })}</time>. Counters use midnight UTC.</span></p> : <p>{loading ? "Loading current usage…" : "Current usage is unavailable."}</p>}<p>Allowances apply immediately after saving. Existing usage stays counted; raising a limit makes the remaining allowance available.</p></div>
    {error ? <p role="alert" className="mt-3 text-xs text-rose-700">Current usage could not be refreshed. {usage ? "The last successful reading is shown." : "You can still edit limits."} <button type="button" onClick={() => void load()} className="underline">Try again</button></p> : null}
  </section>;
}
