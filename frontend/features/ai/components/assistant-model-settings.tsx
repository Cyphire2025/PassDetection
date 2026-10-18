"use client";

import type { AssistantConfiguration } from "../settings-api";

function Choice<K extends keyof AssistantConfiguration>({ label, field, value, options, onChange }: {
  label: string; field: K; value: AssistantConfiguration; options: readonly { id: string; label: string }[]; onChange: (value: AssistantConfiguration) => void;
}) {
  return <label className="block text-sm text-slate-700"><span className="mb-2 block font-medium">{label}</span><select className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-blue-500" value={String(value[field])} onChange={(event) => { const selected = options.find((option) => option.id === event.target.value); if (selected) onChange({ ...value, [field]: selected.id }); }}>{options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}</select></label>;
}

export function AssistantModelSettings({ value, onChange }: { value: AssistantConfiguration; onChange: (value: AssistantConfiguration) => void }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-6"><h3 className="text-sm font-semibold text-slate-900">Models & voice</h3>
    <div className="mt-5 grid gap-5 md:grid-cols-2">{value.provider === "gemini" ? <>
      <Choice label="Chat & document model" field="gemini_model" value={value} onChange={onChange} options={[{ id: "gemini-3.8-flash", label: "Gemini 3.8 Flash — recommended" }, { id: "gemini-3.1-pro-preview", label: "Gemini 3.1 Pro Preview" }, { id: "gemini-3.1-flash-lite", label: "Gemini 3.1 Flash-Lite — economical" }]} />
      <Choice label="Native voice model" field="gemini_live_model" value={value} onChange={onChange} options={[{ id: "gemini-3.8-live", label: "Gemini 3.8 Live — responsive conversation" }, { id: "gemini-3.8-live-extended-thinking", label: "Gemini 3.8 Live — extended thinking" }, { id: "gemini-3.1-flash-live-preview", label: "Gemini 3.1 Flash Live Preview" }]} />
      <Choice label="Voice" field="gemini_voice" value={value} onChange={onChange} options={["Zephyr", "Kore", "Puck", "Charon", "Aoede"].map((id) => ({ id, label: id }))} />
      <Choice label="Image model" field="gemini_image_model" value={value} onChange={onChange} options={[{ id: "gemini-3.1-flash-image", label: "Gemini 3.1 Flash Image" }, { id: "gemini-3.1-flash-lite-image", label: "Gemini 3.1 Flash Lite Image" }]} />
      <Choice label="Chat reasoning" field="reasoning_effort" value={value} onChange={onChange} options={[{ id: "high", label: "High — deeper analysis" }, { id: "medium", label: "Medium — balanced" }, { id: "low", label: "Low — faster replies" }]} />
    </> : <>
      <div><span className="text-sm font-medium text-slate-700">Chat model</span><p className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">GPT-6 Luna · high reasoning</p></div>
      <Choice label="Spoken replies" field="openai_speech_model" value={value} onChange={onChange} options={[{ id: "", label: "Text replies only" }, { id: "gpt-realtime-2.1-mini", label: "GPT-Realtime-2.1 Mini" }, { id: "gpt-realtime-2.1", label: "GPT-Realtime-2.1" }]} />
      <Choice label="OpenAI voice" field="openai_voice" value={value} onChange={onChange} options={["marin", "cedar", "alloy", "coral", "sage"].map((id) => ({ id, label: id.charAt(0).toUpperCase() + id.slice(1) }))} />
    </>}</div>
    <p className="mt-5 text-xs leading-6 text-slate-500">{value.provider === "gemini" ? "Voice conversations send audio directly to Gemini Live and receive spoken audio back. Chat and uploaded-file analysis use the selected chat model. Read-aloud uses Gemini 3.1 Flash TTS." : "Luna handles dashboard reasoning. Recorded voice messages use transcription and the selected speech renderer."} <a href={value.provider === "gemini" ? "https://ai.google.dev/gemini-api/docs/pricing" : "https://developers.openai.com/api/docs/pricing"} target="_blank" rel="noreferrer" className="font-medium text-blue-700 underline underline-offset-2">View provider pricing</a></p>
  </section>;
}
