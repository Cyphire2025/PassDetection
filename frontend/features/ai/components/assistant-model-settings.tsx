"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { assistantMessage } from "../api";
import { aiSettingsApi, type AssistantConfiguration, type ModelCatalog, type ModelOption } from "../settings-api";

const selectClass = "h-11 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-blue-500 disabled:bg-slate-50 disabled:text-slate-500";

export function selectedModels(value: AssistantConfiguration) {
  return {
    chat: value.chat_model || (value.provider === "gemini" ? `gemini:${value.gemini_model}` : "openai:gpt-6-luna"),
    voice: value.voice_model || (value.provider === "openai" ? `openai:${value.openai_speech_model || "gpt-realtime-2.1-mini"}` : `gemini:${value.gemini_live_model}`),
  };
}

function ModelChoice({ label, selected, options, loading, onChange }: { label: string; selected: string; options: ModelOption[]; loading: boolean; onChange: (model: ModelOption) => void }) {
  return <label className="block min-w-0 text-sm text-slate-700"><span className="mb-2 block font-medium">{label}</span>
    <select className={selectClass} value={selected} disabled={loading} onChange={(event) => { const model = options.find((item) => item.id === event.target.value); if (model?.available) onChange(model); }}>
      {!options.some((item) => item.id === selected) ? <option value={selected}>{selected.split(":").slice(1).join(":")} · saved selection</option> : null}
      {(["openai", "gemini"] as const).map((provider) => <optgroup key={provider} label={provider === "openai" ? "OpenAI" : "Google Gemini"}>
        {options.filter((item) => item.provider === provider).map((model) => <option key={model.id} value={model.id} disabled={!model.available}>{model.label}{model.available ? "" : " · availability not verified"}</option>)}
      </optgroup>)}
    </select>
  </label>;
}

function ReasoningChoice({ label, value, model, onChange }: { label: string; value: string; model?: ModelOption; onChange: (effort: string) => void }) {
  const options = model?.reasoning ?? [];
  return <label className="block text-sm text-slate-700"><span className="mb-2 block font-medium">{label}</span>
    <select className={selectClass} value={options.includes(value) ? value : ""} disabled={!options.length} onChange={(event) => onChange(event.target.value)}>
      <option value="">{options.length ? "Model default" : "Automatic · no adjustable reasoning"}</option>
      {options.map((effort) => <option key={effort} value={effort}>{effort.charAt(0).toUpperCase() + effort.slice(1)}</option>)}
    </select>
  </label>;
}

export function AssistantModelSettings({ value, onChange, revision = 0 }: { value: AssistantConfiguration; onChange: (value: AssistantConfiguration) => void; revision?: number }) {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [loadedRequest, setLoadedRequest] = useState("");
  const [error, setError] = useState("");
  const loading = loadedRequest !== `${revision}:${refresh}`;
  useEffect(() => {
    const abort = new AbortController();
    void aiSettingsApi.models(abort.signal).then((result) => {
      if (!abort.signal.aborted) {
        if (!Array.isArray(result.models) || !Array.isArray(result.providers)) throw new Error("Model catalog is unavailable.");
        setCatalog(result); setError("");
      }
    }).catch((cause) => { if (!abort.signal.aborted) setError(assistantMessage(cause, "Models could not be loaded. Your saved choices are preserved.")); })
      .finally(() => { if (!abort.signal.aborted) setLoadedRequest(`${revision}:${refresh}`); });
    return () => abort.abort();
  }, [revision, refresh]);
  const selected = selectedModels(value);
  const models = catalog?.models ?? [];
  const chat = models.find((model) => model.id === selected.chat);
  const voice = models.find((model) => model.id === selected.voice);
  const voiceName = value.voice_name || (selected.voice.startsWith("gemini:") ? value.gemini_voice : value.openai_voice);
  const chatReasoning = value.chat_model ? value.chat_reasoning || "" : value.provider === "gemini" ? value.reasoning_effort : value.openai_reasoning_effort;
  return <section className="rounded-xl border border-slate-200 bg-white p-6" aria-busy={loading} aria-labelledby="ai-model-settings-heading">
    <div className="flex items-center justify-between gap-3"><div><h3 id="ai-model-settings-heading" className="text-sm font-semibold text-slate-900">Models &amp; voice</h3><p className="mt-2 text-xs leading-5 text-slate-500">Choose any compatible model available to your saved OpenAI and Gemini keys.</p></div>
      <button type="button" className="rounded-lg border border-slate-200 p-2.5 text-slate-600 disabled:opacity-40" disabled={loading} aria-label="Refresh available models" onClick={() => setRefresh((current) => current + 1)}>{loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}</button>
    </div>
    <div className="mt-5 grid gap-5 md:grid-cols-2">
      <ModelChoice label="Chat & document model" selected={selected.chat} options={models.filter((model) => model.kind === "chat")} loading={loading} onChange={(model) => onChange({ ...value, chat_model: model.id, chat_reasoning: "" })} />
      <ReasoningChoice label="Chat reasoning" model={loading ? undefined : chat} value={chatReasoning} onChange={(chat_reasoning) => onChange({ ...value, chat_model: selected.chat, chat_reasoning })} />
      <ModelChoice label="Native voice model" selected={selected.voice} options={models.filter((model) => model.kind === "voice")} loading={loading} onChange={(model) => { const preset = model.voices.find((item) => item.id === voiceName) ?? model.voices[0]; onChange({ ...value, voice_model: model.id, voice_reasoning: model.reasoning.includes("low") ? "low" : "", voice_name: preset?.id || "", voice_presentation: preset?.appearance ?? null }); }} />
      <label className="block text-sm text-slate-700"><span className="mb-2 block font-medium">Voice</span><select className={selectClass} value={voiceName} disabled={loading || !voice?.voices.length} onChange={(event) => onChange({ ...value, voice_model: selected.voice, voice_name: event.target.value, voice_presentation: voice?.voices.find((item) => item.id === event.target.value)?.appearance ?? null })}>
        {!voice?.voices.some((item) => item.id === voiceName) ? <option value={voiceName}>{voiceName} · saved voice</option> : null}
        {voice?.voices.map((item) => <option key={item.id} value={item.id}>{item.label} · {item.appearance === "male" ? "Male" : "Female"}</option>)}
      </select></label>
      <ReasoningChoice label="Voice reasoning" model={loading ? undefined : voice} value={value.voice_reasoning || ""} onChange={(voice_reasoning) => onChange({ ...value, voice_model: selected.voice, voice_reasoning })} />
    </div>
    <p className="mt-5 text-xs leading-6 text-slate-500">Voice conversations stream spoken replies automatically. Lower reasoning levels favor faster replies. The human hologram follows the selected voice. Model and voice changes take effect in a new voice session.</p>
    {selected.voice.startsWith("openai:gpt-live-") ? <p className="mt-2 text-xs leading-5 text-slate-500">GPT-Live supports continuous voice conversations. Read-aloud for existing typed replies is available with Realtime and Gemini models.</p> : null}
    {error ? <p role="alert" className="mt-3 text-sm text-rose-700">{error}</p> : null}
    {catalog?.providers.filter((provider) => provider.status !== "ready").map((provider) => <p key={provider.provider} className="mt-2 text-xs text-slate-500">{provider.provider === "openai" ? "OpenAI" : "Gemini"}: {provider.message}</p>)}
  </section>;
}
