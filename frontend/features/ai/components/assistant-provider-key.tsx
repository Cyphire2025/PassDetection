"use client";

import { KeyRound, Loader2, RefreshCw } from "lucide-react";
import type { ProviderName } from "../settings-api";

type Props = { provider: ProviderName; stored: boolean; value: string; remove: boolean; saving: boolean; checking: boolean; dirty: boolean; onChange: (value: string) => void; onRemove: () => void; onCheck: () => void };

export function AssistantProviderKey({ provider, stored, value, remove, saving, checking, dirty, onChange, onRemove, onCheck }: Props) {
  const name = provider === "gemini" ? "Gemini AI Studio API key" : "OpenAI API key";
  return <div role="group" aria-label={`${provider === "gemini" ? "Gemini" : "OpenAI"} connection`} className="mt-5 rounded-lg border border-slate-200 p-4">
    <div className="flex items-center justify-between gap-4"><label htmlFor={`assistant-provider-key-${provider}`} className="text-sm font-medium text-slate-700">{name}</label><span className={`rounded-full px-2 py-1 text-xs ${stored && !remove ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{remove ? "Removal pending" : stored ? "Key stored" : "Not connected"}</span></div>
    <div className="relative mt-2"><KeyRound size={17} className="absolute left-3 top-3.5 text-slate-400" /><input id={`assistant-provider-key-${provider}`} type="password" autoComplete="off" spellCheck={false} value={value} onChange={(event) => onChange(event.target.value)} placeholder={stored ? "Paste a new key to replace the saved key" : "Paste your API key"} className="h-12 w-full rounded-lg border border-slate-200 bg-white pl-10 pr-3 text-sm outline-blue-500" /></div>
    <div className="mt-4 flex flex-wrap items-center gap-4"><button type="button" onClick={onCheck} disabled={checking || saving || dirty || !stored} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 disabled:opacity-40">{checking ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}Check saved key</button>{stored ? <button type="button" disabled={saving} onClick={onRemove} className="text-xs text-rose-700">{remove ? "Keep saved key" : "Remove saved key"}</button> : null}</div>
  </div>;
}
