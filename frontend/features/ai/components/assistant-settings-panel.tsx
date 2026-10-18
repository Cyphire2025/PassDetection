"use client";

import { Check, KeyRound, Loader2, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { assistantMessage } from "../api";
import { aiSettingsApi, DEFAULT_USAGE_LIMITS, type AssistantConfiguration, type ProviderName, type SettingsSnapshot } from "../settings-api";
import { AssistantAccessSettings } from "./assistant-access-settings";
import { AssistantModelSettings } from "./assistant-model-settings";
import { AssistantUsageSettings, validUsageLimits } from "./assistant-usage-settings";

export function AssistantSettingsPanel() {
  const user = useAuthStore(selectUser);
  if (user?.role !== "super_admin") return <div role="alert" className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">Only super administrators can manage AI settings.</div>;
  return <AuthorizedAssistantSettings key={`${user.id}:${user.role}:${user.agency_id}`} />;
}

function AuthorizedAssistantSettings() {
  const [saved, setSaved] = useState<SettingsSnapshot | null>(null);
  const [configuration, setConfiguration] = useState<AssistantConfiguration | null>(null);
  const [keys, setKeys] = useState<Record<ProviderName, string>>({ gemini: "", openai: "" });
  const [remove, setRemove] = useState<Record<ProviderName, boolean>>({ gemini: false, openai: false });
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const reload = useCallback(async (signal?: AbortSignal) => {
    try { const result = await aiSettingsApi.get(signal); if (!signal?.aborted) { setSaved(result); setConfiguration(result.configuration); setError(""); } }
    catch (cause) { if (!signal?.aborted) setError(assistantMessage(cause, "AI settings could not be loaded.")); }
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    // Initial loading subscribes directly to the asynchronous server result.
    void aiSettingsApi.get(abort.signal).then((result) => {
      if (!abort.signal.aborted) { setSaved(result); setConfiguration(result.configuration); }
    }).catch((cause) => { if (!abort.signal.aborted) setError(assistantMessage(cause, "AI settings could not be loaded.")); });
    return () => abort.abort();
  }, []);
  const dirty = Boolean(saved && configuration && (JSON.stringify(saved.configuration) !== JSON.stringify(configuration) || keys.gemini || keys.openai || remove.gemini || remove.openai));
  const save = async () => {
    if (!saved || !configuration || saving || !validUsageLimits(configuration.usage_limits)) return;
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await aiSettingsApi.save({ expected_revision: saved.revision, configuration,
        ...(keys.gemini.trim() ? { gemini_api_key: keys.gemini.trim() } : {}), ...(keys.openai.trim() ? { openai_api_key: keys.openai.trim() } : {}),
        clear_gemini_key: remove.gemini, clear_openai_key: remove.openai });
      setKeys({ gemini: "", openai: "" }); setRemove({ gemini: false, openai: false }); setSaved(result); setConfiguration(result.configuration);
      setNotice("AI settings saved."); window.dispatchEvent(new Event("assistant-settings-changed"));
    } catch (cause) { setError(assistantMessage(cause, "AI settings could not be saved.")); }
    finally { setSaving(false); }
  };
  const check = async () => {
    if (!configuration || checking) return;
    setChecking(true); setError(""); setNotice("");
    try { setNotice((await aiSettingsApi.check(configuration.provider)).message); }
    catch (cause) { setError(assistantMessage(cause, "The connection could not be verified.")); }
    finally { setChecking(false); }
  };
  if (!saved || !configuration) return <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-500">{error ? <><p role="alert">{error}</p><button type="button" onClick={() => void reload()} className="mt-3 text-blue-700">Try again</button></> : <span role="status" className="inline-flex items-center gap-2"><Loader2 size={15} className="animate-spin" />Loading AI settings…</span>}</div>;
  const provider = configuration.provider;
  return <div className="space-y-5" data-testid="assistant-settings"><fieldset disabled={saving} className="contents space-y-5">
    <section className="rounded-xl border border-slate-200 bg-white p-6">
      <div className="flex items-center justify-between gap-5">
        <div><h2 className="text-base font-semibold text-slate-950">Global Connects AI</h2><p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">Manage your private dashboard assistant, provider connection and team access.</p></div>
        <AssistantEnableSwitch enabled={configuration.enabled} onChange={(enabled) => setConfiguration({ ...configuration, enabled })} />
      </div>
      <p className="mt-5 flex items-start gap-2 rounded-lg bg-slate-50 p-3 text-xs leading-6 text-slate-500"><ShieldCheck size={16} className="mt-1 shrink-0" />AI can read permitted dashboard information. It cannot change business records or send messages.</p>
    </section>
    <section className="rounded-xl border border-slate-200 bg-white p-6"><h3 className="text-sm font-semibold text-slate-900">Provider connection</h3><div className="mt-4 grid grid-cols-2 gap-3">{(["gemini", "openai"] as const).map((item) => <button key={item} type="button" aria-pressed={provider === item} onClick={() => setConfiguration({ ...configuration, provider: item })} className={`rounded-lg border p-4 text-left transition ${provider === item ? "border-blue-300 bg-blue-50/60 ring-1 ring-blue-100" : "border-slate-200 hover:bg-slate-50"}`}><span className="block text-sm font-semibold text-slate-800">{item === "gemini" ? "Google Gemini" : "OpenAI"}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{item === "gemini" ? "AI Studio key · native voice" : "GPT-6 Luna · add when ready"}</span></button>)}</div>
      <div className="mt-5 flex items-center justify-between gap-4"><label htmlFor="assistant-provider-key" className="text-sm font-medium text-slate-700">{provider === "gemini" ? "Gemini AI Studio API key" : "OpenAI API key"}</label><span className={`rounded-full px-2 py-1 text-xs ${saved.credentials[provider] && !remove[provider] ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{remove[provider] ? "Removal pending" : saved.credentials[provider] ? "Key stored" : "Not connected"}</span></div>
      <div className="relative mt-2"><KeyRound size={17} className="absolute left-3 top-3.5 text-slate-400" /><input id="assistant-provider-key" type="password" autoComplete="off" spellCheck={false} value={keys[provider]} onChange={(event) => { setKeys({ ...keys, [provider]: event.target.value }); setRemove({ ...remove, [provider]: false }); }} placeholder={saved.credentials[provider] ? "Paste a new key to replace the saved key" : "Paste your API key"} className="h-12 w-full rounded-lg border border-slate-200 bg-white pl-10 pr-3 text-sm outline-blue-500" /></div>
      <p className="mt-2 text-xs leading-6 text-slate-500">Saved keys are encrypted on the server and stay hidden after saving. An empty field keeps your current key.</p>
      <div className="mt-4 flex flex-wrap items-center gap-4"><button type="button" onClick={() => void check()} disabled={checking || saving || dirty || !saved.credentials[provider]} className="inline-flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-xs font-medium text-slate-700 disabled:opacity-40">{checking ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}Check saved key</button>{saved.credentials[provider] ? <button type="button" disabled={saving} onClick={() => { setKeys({ ...keys, [provider]: "" }); setRemove({ ...remove, [provider]: !remove[provider] }); }} className="text-xs text-rose-700">{remove[provider] ? "Keep saved key" : "Remove saved key"}</button> : null}</div>
    </section>
    <AssistantModelSettings value={configuration} onChange={setConfiguration} />
    <AssistantUsageSettings value={configuration.usage_limits ?? DEFAULT_USAGE_LIMITS} onChange={(usage_limits) => setConfiguration({ ...configuration, usage_limits })} revision={saved.revision} />
    <AssistantAccessSettings key={saved.revision} value={configuration} people={saved.granted_users} onChange={setConfiguration} />
    <div className="sticky bottom-0 z-10 rounded-xl border border-slate-200 bg-white/95 p-4 shadow-sm backdrop-blur"><div className="flex flex-wrap items-center justify-between gap-4"><div className="min-w-0 text-sm">{error ? <p role="alert" className="text-rose-700">{error}</p> : notice ? <p role="status" className="inline-flex items-center gap-2 text-emerald-700"><Check size={16} />{notice}</p> : <p className="text-slate-500">{dirty ? "You have unsaved changes." : "Your settings are up to date."}</p>}</div><div className="flex gap-3"><button type="button" onClick={() => void reload()} disabled={saving} className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm text-slate-600">Reload</button><button type="button" onClick={() => void save()} disabled={saving || !dirty || !validUsageLimits(configuration.usage_limits)} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-40">{saving ? <Loader2 size={15} className="animate-spin" /> : null}Save AI settings</button></div></div></div>
  </fieldset></div>;
}

function AssistantEnableSwitch({ enabled, onChange }: { enabled: boolean; onChange: (value: boolean) => void }) {
  return <button type="button" role="switch" aria-checked={enabled} aria-label="Enable Global Connects AI"
    onClick={() => onChange(!enabled)} className="flex shrink-0 items-center gap-3 rounded-lg p-1 text-sm font-medium text-slate-700 outline-blue-500 focus-visible:ring-2 focus-visible:ring-blue-500">
    <span>{enabled ? "On" : "Off"}</span>
    <span aria-hidden="true" className={`relative h-6 w-11 rounded-full transition-colors ${enabled ? "bg-blue-600" : "bg-slate-300"}`}>
      <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white transition-transform ${enabled ? "translate-x-5" : ""}`} />
    </span>
  </button>;
}
