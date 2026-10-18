"use client";

import { ArrowLeft, ArrowUpRight, ChevronLeft, Library, Loader2, MessageSquare, Mic, Moon, Plus, Settings2, Square, Sun, VolumeX, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { LiquidSculptureHero } from "@/components/ui/liquid-sculpture-hero";
import { DEFAULT_APPEARANCE, type SculptureHandle } from "@/components/ui/liquid-sculpture/types";
import { useAssistant } from "../hooks/use-assistant";
import { useAssistantAudio } from "../hooks/use-assistant-audio";
import { useNativeVoice } from "../hooks/use-native-voice";
import { useAssistantTheme } from "../hooks/use-assistant-theme";
import type { Asset, VisualState } from "../types";
import { AssistantComposer } from "./assistant-composer";
import { ConversationThread } from "./conversation-thread";
import { ImageReveal } from "./image-reveal";
import { WorkspaceDrawer } from "./workspace-drawer";
import { SculptureAppearanceControl } from "./sculpture-appearance";
import styles from "./workspace.module.css";

const MOTES = Array.from({ length: 54 }, (_, index) => ({ left: `${(index * 61.803 + 9) % 100}%`, top: `${(index * 37.179 + 7) % 100}%`, delay: `${index * -2.7}s`, duration: `${24 + index % 9 * 4}s`, size: `${index % 11 === 0 ? 5 : index % 4 === 0 ? 3.5 : 1.5 + index % 3 * .5}px` }));

export function AssistantWorkspace({ onBack }: { onBack?: () => void } = {}) {
  const router = useRouter();
  const { dark, toggle: toggleTheme } = useAssistantTheme();
  const [drawer, setDrawer] = useState<"library" | "history" | null>(null);
  const [draft, setDraft] = useState("");
  const [activeImage, setActiveImage] = useState<Asset | null>(null);
  const [images, setImages] = useState<Asset[]>([]);
  const [voiceFiles, setVoiceFiles] = useState<Asset[]>([]);
  const [appearance, setAppearance] = useState(DEFAULT_APPEARANCE);
  const [sculptureRenderer, setSculptureRenderer] = useState<"webgl" | "image" | null>(null);
  const [conversationOpen, setConversationOpen] = useState(false);
  const conversationPanel = useRef<HTMLDivElement>(null);
  const conversationTab = useRef<HTMLButtonElement>(null);
  const speechAllowed = useRef(false);
  const sendVoice = useRef<(text: string) => void>(() => undefined);
  const audio = useAssistantAudio(useCallback((text: string) => sendVoice.current(text), []));
  const speak = audio.speak;
  const answer = useCallback((text: string) => { if (speechAllowed.current) void speak(text); }, [speak]);
  const newImage = useCallback((image: Asset) => { setImages((current) => [...current.filter((item) => item.id !== image.id), image]); setActiveImage((current) => current || image); }, []);
  const assistant = useAssistant(answer, newImage);
  const stopMicrophone = audio.stopInput;
  const finishNative = assistant.finishNative;
  const onNativeStopped = useCallback(() => { stopMicrophone(true); finishNative(); }, [stopMicrophone, finishNative]);
  const native = useNativeVoice(assistant.receiveNative, onNativeStopped);
  const { stop: stopNative } = native;
  const send = assistant.send;
  const signedIn = assistant.access === "ready";
  const accountKey = `${assistant.status?.account_id || "public"}:${assistant.status?.account_scope || "default"}`;
  const [workspaceAccount, setWorkspaceAccount] = useState(accountKey);
  if (workspaceAccount !== accountKey) {
    setWorkspaceAccount(accountKey); setImages([]); setActiveImage(null); setDrawer(null); setVoiceFiles([]); setConversationOpen(false); setAppearance(DEFAULT_APPEARANCE);
  }
  const ready = signedIn && Boolean(assistant.status?.configured);
  const nativeEnabled = Boolean(assistant.status?.native_voice);
  const nativeSession = native.active || native.connecting;
  const listening = audio.microphone.status === "listening";
  const requesting = audio.microphone.status === "requesting";
  const speaking = native.speaking || audio.speaking;
  const phase = nativeSession ? native.speaking ? "speaking" : native.thinking || native.connecting ? "thinking" : "listening"
    : listening ? "listening" : audio.speaking ? "speaking" : assistant.busy || audio.transcribing || audio.preparing ? "thinking" : "idle";
  const presentation = useRef<VisualState>({ phase: "idle", reply: false, reveal: 0, revealWidth: 600, revealHeight: 370 });
  const sculpture = useRef<SculptureHandle>(null);
  const renderReveal = useCallback(() => sculpture.current?.invalidate(), []);
  const level = useRef(0);
  const voiceControl = useRef<HTMLDivElement>(null);
  useEffect(() => { speechAllowed.current = Boolean(assistant.status?.speech_configured); }, [assistant.status?.speech_configured]);
  useEffect(() => { sendVoice.current = (text) => { void send(text); }; }, [send]);
  useEffect(() => { stopNative(); }, [accountKey, stopNative]);
  useEffect(() => {
    if (!signedIn || (nativeSession && audio.microphone.status !== "listening")) stopNative();
  }, [signedIn, nativeSession, audio.microphone.status, stopNative]);
  useEffect(() => {
    presentation.current.phase = phase;
    presentation.current.reply = phase === "speaking" || audio.preparing || (assistant.busy && assistant.messages.some((message) => message.streaming && message.text.length > 0));
  }, [phase, audio.preparing, assistant.busy, assistant.messages]);
  useEffect(() => {
    if (!signedIn) return;
    let frame = 0;
    const paint = () => {
      level.current = native.speaking ? native.playbackLevel.current : audio.speaking ? audio.playbackLevel.current : listening ? audio.microphone.levelRef.current : 0;
      voiceControl.current?.style.setProperty("--voice-level", String(level.current));
      frame = requestAnimationFrame(paint);
    };
    frame = requestAnimationFrame(paint); return () => cancelAnimationFrame(frame);
  }, [signedIn, listening, native.speaking, native.playbackLevel, audio.speaking, audio.microphone.levelRef, audio.playbackLevel]);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const closeImage = useCallback(() => setActiveImage(null), []);
  const openImage = useCallback((image: Asset, collection?: Asset[]) => { if (collection) setImages(collection); else setImages((current) => current.some((item) => item.id === image.id) ? current : [...current, image]); setActiveImage(image); }, []);
  const { stopInput, stopPlayback } = audio;
  const { stop: stopAssistant } = assistant;
  const stopEverything = useCallback(() => { stopNative(); stopInput(true); stopPlayback(); stopAssistant(); }, [stopNative, stopInput, stopPlayback, stopAssistant]);
  const hideConversation = () => { setConversationOpen(false); requestAnimationFrame(() => conversationTab.current?.focus({ preventScroll: true })); };
  const showConversation = () => { setConversationOpen(true); requestAnimationFrame(() => conversationPanel.current?.querySelector<HTMLButtonElement>("[data-conversation-close]")?.focus({ preventScroll: true })); };
  const deleteConversation = async (id: string) => {
    if (id === assistant.conversationId) stopEverything();
    const cleared = await assistant.deleteConversation(id);
    if (cleared) { setActiveImage(null); setImages([]); }
  };
  const back = useCallback(() => { stopEverything(); if (onBack) onBack(); else router.push("/dashboard"); }, [onBack, router, stopEverything]);
  useEffect(() => { window.addEventListener("assistant-request-back", back); return () => window.removeEventListener("assistant-request-back", back); }, [back]);
  const newConversation = () => { stopEverything(); assistant.newConversation(); setActiveImage(null); setImages([]); setConversationOpen(false); };
  const microphone = async () => {
    if (nativeSession || listening || requesting) { stopNative(); audio.stopInput(); return; }
    audio.warmAudio(); native.warm();
    if (nativeEnabled && ready) {
      const conversation = assistant.beginNative(); if (!conversation) return;
      await audio.startInput(false, true);
      const stream = audio.microphone.getStream();
      if (stream) native.start(stream, conversation, voiceFiles.map((file) => file.id));
    } else await audio.startInput(ready);
  };
  const label = native.connecting ? "Connecting voice…" : phase === "listening" ? "Listening to you" : phase === "speaking" ? "Speaking with you" : phase === "thinking" ? assistant.progress || "Thinking…" : "";
  const error = native.error || audio.error || assistant.error;

  const panelOpen = assistant.messages.length > 0 && conversationOpen;
  return <main className={styles.page} aria-label="Global Connects AI workspace" data-theme={dark ? "dark" : "light"} data-phase={phase} data-has-conversation={assistant.messages.length > 0} data-conversation-open={panelOpen} data-image-open={Boolean(activeImage)}>
    <div className={styles.atmosphere} aria-hidden="true" data-testid="assistant-atmosphere">{MOTES.map((mote, index) => <i key={index} className={index % 13 === 0 ? styles.doubleMote : undefined} style={{ left: mote.left, top: mote.top, animationDelay: mote.delay, animationDuration: mote.duration, width: mote.size, height: mote.size }} />)}</div>
    <header className={styles.header}>
      <div className={styles.brandGroup}><button type="button" onClick={back} className={styles.backButton} aria-label="Back to workspace"><ArrowLeft size={19} /></button><div className={styles.brand} aria-label="Global Connects"><span className={styles.monogram}>gc<ArrowUpRight size={16} strokeWidth={2.5} /></span><span>Global Connects<small>YOUR TRAVEL WORKSPACE</small></span></div></div>
      {signedIn ? <div className={styles.headerActions}>
        <span className={styles.connectionDot} data-connected={Boolean(assistant.observedAt)} aria-label={assistant.observedAt ? "Workspace connected" : "Connecting workspace"} />
        <button type="button" className={styles.iconButton} onClick={toggleTheme} aria-label={dark ? "Switch to light mode" : "Switch to dark mode"} aria-pressed={dark}>{dark ? <Sun size={18} /> : <Moon size={18} />}</button>
        <SculptureAppearanceControl key={accountKey} value={appearance} onChange={setAppearance} renderer={sculptureRenderer} />
        <button type="button" className={styles.iconButton} onClick={() => setDrawer("library")} aria-label="Open library"><Library size={18} /></button>
        <button type="button" className={styles.iconButton} onClick={() => setDrawer("history")} aria-label="Open conversations"><MessageSquare size={18} /></button>
        <button type="button" className={styles.iconButton} onClick={newConversation} aria-label="New conversation" disabled={assistant.busy}><Plus size={20} /></button>
        {assistant.status?.can_manage_settings ? <Link href="/settings/ai" className={styles.iconButton} aria-label="AI settings"><Settings2 size={18} /></Link> : null}
      </div> : null}
    </header>
    {signedIn ? <>
      <div className={styles.mainArea}>
        <section className={styles.visualArea} aria-label="Voice-reactive particle sculpture">
          <div className={styles.sculptureStage} data-testid="assistant-stage"><LiquidSculptureHero ref={sculpture} levelRef={level} presentationRef={presentation} dark={dark} appearance={appearance} onRendererChange={setSculptureRenderer} /><ImageReveal asset={activeImage} images={images} presentationRef={presentation} onSelect={setActiveImage} onClosed={closeImage} onProgress={renderReveal} /></div>
          <div className={styles.voiceStatus} ref={voiceControl} data-listening={listening && !speaking} data-testid="assistant-voice-status">
            <button type="button" className={styles.voiceButton} onClick={() => void microphone()} disabled={assistant.busy || audio.transcribing} aria-label={nativeSession ? "End voice conversation" : requesting ? "Cancel microphone request" : listening ? "Finish voice message" : "Start microphone"} aria-pressed={listening || requesting || nativeSession}>
              {requesting || native.connecting || audio.transcribing ? <Loader2 size={20} className={styles.spinner} /> : listening || nativeSession ? <Square size={17} fill="currentColor" /> : <Mic size={23} strokeWidth={1.5} />}
            </button>
            <p role="status" aria-live="polite">{label}</p>
            {speaking ? <button type="button" onClick={() => { stopNative(); audio.stopPlayback(); }} className={styles.quietButton}><VolumeX size={12} />Stop speaking</button> : null}
          </div>
        </section>
        <div className={styles.conversationPanel} ref={conversationPanel} id="assistant-conversation-panel" aria-hidden={!panelOpen} inert={!panelOpen}>
          {assistant.messages.length ? <ConversationThread messages={assistant.messages} progress={assistant.progress} speaking={speaking} speechReady={Boolean(assistant.status?.speech_configured)} onSpeak={(text) => { stopNative(); audio.warmAudio(); void audio.speak(text); }} onImage={openImage} hasEarlier={Boolean(assistant.olderCursor)} loadingHistory={assistant.loadingHistory} onLoadEarlier={() => void assistant.loadEarlier()} onHide={hideConversation} /> : null}
        </div>
        <div className={styles.composerDock}>
          {error ? <div className={styles.errorNotice} role="alert"><span>{error}</span><button type="button" onClick={() => { assistant.setError(""); audio.clearError(); native.clearError(); }} aria-label="Dismiss notice"><X size={13} /></button></div> : null}
          <AssistantComposer key={accountKey} ready={ready} busy={assistant.busy || native.connecting || native.recovering} voiceActive={nativeSession} text={draft} onTextChange={setDraft} onSubmit={(text, files, mode, count) => { if (native.active && mode === "chat") native.sendText(text); else if (nativeSession) native.sendText("Create " + count + " image(s): " + text); else void assistant.send(text, files, mode, count); }} onStop={stopEverything} onWarmAudio={audio.warmAudio} onError={assistant.setError} onAttachmentsChange={setVoiceFiles} />
        </div>
      </div>
      {assistant.messages.length ? <button ref={conversationTab} type="button" className={styles.conversationTab} onClick={showConversation} aria-label="Show conversation" aria-controls="assistant-conversation-panel" aria-expanded={panelOpen} aria-hidden={panelOpen} tabIndex={panelOpen ? -1 : 0}><ChevronLeft size={28} strokeWidth={1.6} /></button> : null}
    </> : <div className={styles.accessState} role="status">{assistant.access === "loading" ? <><Loader2 size={22} className={styles.spinner} /><p>Opening your workspace…</p></> : <><h1>{assistant.access === "guest" ? "Sign in to Global Connects" : "AI access is unavailable"}</h1><p>{assistant.access === "guest" ? "Use your authorized workspace account to continue." : "Your super administrator controls access to this workspace."}</p>{assistant.access === "guest" ? <Link href="/session-restore?from=%2Fai">Sign in<ArrowUpRight size={14} /></Link> : <button type="button" onClick={() => void assistant.refresh()}>Check access again</button>}</>}</div>}
    {drawer && signedIn ? <WorkspaceDrawer key={drawer} kind={drawer} signedIn={signedIn} onClose={closeDrawer} onImage={openImage} onConversation={(id) => { stopEverything(); setConversationOpen(true); void assistant.openConversation(id); }} onNew={newConversation} onDelete={deleteConversation} /> : null}
  </main>;
}
