"use client";

import Image from "next/image";
import { ArrowUp, FileText, ImagePlus, Loader2, Mic, Plus, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { assistantApi, assistantMessage } from "../api";
import type { Asset } from "../types";
import styles from "./composer.module.css";

export function AssistantComposer({ ready, busy, listening, requesting, transcribing, text, onTextChange: setText, onSubmit, onMic, onStop, onWarmAudio, onError }: {
  ready: boolean; busy: boolean; listening: boolean; requesting: boolean; transcribing: boolean;
  text: string; onTextChange: (text: string) => void;
  onSubmit: (text: string, files: Asset[], mode: "chat" | "image", count: number) => void;
  onMic: () => void; onStop: () => void; onWarmAudio: () => void; onError: (message: string) => void;
}) {
  const [files, setFiles] = useState<Asset[]>([]);
  const [uploading, setUploading] = useState(false);
  const [mode, setMode] = useState<"chat" | "image">("chat");
  const [count, setCount] = useState(1);
  const [menu, setMenu] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const menuRoot = useRef<HTMLDivElement>(null);
  const uploads = useRef<AbortController | null>(null);
  useEffect(() => { const element = textarea.current; if (element) { element.style.height = "auto"; element.style.height = `${Math.min(130, element.scrollHeight)}px`; } }, [text]);
  useEffect(() => () => uploads.current?.abort(), []);
  useEffect(() => {
    if (!menu) return;
    const close = (event: PointerEvent) => { if (!menuRoot.current?.contains(event.target as Node)) setMenu(false); };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") setMenu(false); };
    window.addEventListener("pointerdown", close); window.addEventListener("keydown", key);
    return () => { window.removeEventListener("pointerdown", close); window.removeEventListener("keydown", key); };
  }, [menu]);

  const upload = async (selected: FileList | null) => {
    if (!selected || !ready) return;
    const candidates = [...selected];
    if (candidates.length + files.length > 4) { onError("Attach up to four files to one question."); return; }
    if (candidates.some((file) => file.size > (file.name.toLowerCase().endsWith(".pdf") ? 5 : 8) * 1024 * 1024)) { onError("PDFs can be up to 5 MB; other files can be up to 8 MB."); return; }
    const abort = new AbortController(); uploads.current = abort; setUploading(true); setMenu(false);
    try { for (const file of candidates) { const asset = await assistantApi.upload(file, abort.signal); setFiles((current) => [...current, asset]); } }
    catch (cause) { if (!abort.signal.aborted) onError(assistantMessage(cause, "This file could not be uploaded. Please try again.")); }
    finally { setUploading(false); if (input.current) input.current.value = ""; }
  };
  const submit = () => {
    if (!text.trim() || !ready || busy || uploading) return;
    onWarmAudio(); onSubmit(text.trim(), files, mode, count); setText(""); setFiles([]);
  };
  return <div className={styles.composer} data-listening={listening}>
    <div className={styles.inputShell}>
      {files.length ? <div className={styles.attachments}>{files.map((file) => <div className={styles.attachment} key={file.id}>{file.mime.startsWith("image/") ? <Image src={file.url} alt="" width={32} height={32} unoptimized /> : <FileText size={21} />}<span>{file.name}</span><button type="button" onClick={() => setFiles((current) => current.filter((item) => item.id !== file.id))} aria-label={`Detach ${file.name}`}><X size={12} /></button></div>)}</div> : null}
      {mode === "image" ? <div className={styles.modeChip}><ImagePlus size={13} /><span>Create images</span><select value={count} onChange={(event) => setCount(Number(event.target.value))} aria-label="Number of images">{[1, 2, 3, 4].map((value) => <option key={value} value={value}>{value} image{value > 1 ? "s" : ""}</option>)}</select><button type="button" onClick={() => setMode("chat")} aria-label="Return to chat"><X size={12} /></button></div> : null}
      <textarea ref={textarea} value={text} onChange={(event) => setText(event.target.value)} maxLength={8000} rows={1} aria-label={mode === "image" ? "Describe your image" : "Message Global Connects"} placeholder={listening ? "Listening to you…" : mode === "image" ? "Describe what you’d like to create…" : "Ask Global Connects anything about your workspace…"}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }} />
      <div className={styles.toolbar}>
        <div className={styles.tools} ref={menuRoot}>
          <button type="button" className={styles.toolButton} aria-label="Add files or create images" aria-expanded={menu} onClick={() => setMenu((value) => !value)}><Plus size={20} /></button>
          {menu ? <div className={styles.addMenu}><button type="button" disabled={!ready || uploading || files.length >= 4} onClick={() => input.current?.click()}><FileText size={16} /><span>Add files<small>PDF, images, documents & spreadsheets</small></span></button><button type="button" onClick={() => { setMode("image"); setMenu(false); textarea.current?.focus(); }}><ImagePlus size={16} /><span>Create images<small>Bring an idea into focus</small></span></button></div> : null}
          <input ref={input} className={styles.hiddenInput} type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.webp,.txt,.md,.csv,.json,.docx,.xlsx" onChange={(event) => void upload(event.target.files)} aria-label="Upload attachments" tabIndex={-1} />
          <span className={styles.contextLabel}>{uploading ? <><Loader2 size={12} className={styles.spinner} />Checking your file…</> : transcribing ? <><Loader2 size={12} className={styles.spinner} />Turning speech into words…</> : <><span className={styles.contextDot} />Read-only workspace</>}</span>
        </div>
        <div className={styles.sendTools}>
          <button type="button" className={`${styles.toolButton} ${listening ? styles.micActive : ""}`} onClick={onMic} disabled={busy || transcribing} aria-label={listening ? "Finish voice message" : requesting ? "Cancel microphone request" : "Start microphone"} aria-pressed={listening || requesting}>{requesting || transcribing ? <Loader2 size={18} className={styles.spinner} /> : listening ? <Square size={15} fill="currentColor" /> : <Mic size={19} />}</button>
          <button type="button" className={styles.sendButton} onClick={busy ? onStop : submit} disabled={!busy && (!ready || !text.trim() || uploading)} aria-label={busy ? "Stop response" : mode === "image" ? "Create images" : "Send message"}>{busy ? <Square size={13} fill="currentColor" /> : <ArrowUp size={18} />}</button>
        </div>
      </div>
    </div>
    <p className={styles.disclaimer}>{listening ? ready ? "Speak naturally. Audio is sent for transcription after a brief pause." : "Voice preview. Your microphone audio stays on this device." : "Global Connects can make mistakes. Check important travel details."}</p>
  </div>;
}
