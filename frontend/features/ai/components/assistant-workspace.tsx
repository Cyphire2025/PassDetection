"use client";

import { ArrowUpRight, AudioLines, Library, LogIn, MessageSquare, Plus, RefreshCw, Volume2, VolumeX, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { LiquidSculptureHero } from "@/components/ui/liquid-sculpture-hero";
import { useAssistant } from "../hooks/use-assistant";
import { useAssistantAudio } from "../hooks/use-assistant-audio";
import type { Asset, VisualState } from "../types";
import { AssistantComposer } from "./assistant-composer";
import { ConversationThread } from "./conversation-thread";
import { ImageReveal } from "./image-reveal";
import { WorkspaceDrawer } from "./workspace-drawer";
import styles from "./workspace.module.css";

const SUGGESTIONS = ["Which documents are still pending?", "Give me a group overview", "Help me plan the next departure"];
const MOTES = Array.from({ length: 18 }, (_, index) => ({ left: `${(index * 37 + 11) % 100}%`, top: `${(index * 23 + 13) % 94}%`, delay: `${index * -2.7}s`, duration: `${22 + index % 6 * 5}s`, size: `${index % 5 === 0 ? 5 : index % 3 === 0 ? 3 : 2}px` }));

export function AssistantWorkspace() {
  const [drawer, setDrawer] = useState<"library" | "history" | null>(null);
  const [draft, setDraft] = useState("");
  const [activeImage, setActiveImage] = useState<Asset | null>(null);
  const [images, setImages] = useState<Asset[]>([]);
  const [voiceReply, setVoiceReply] = useState(true);
  const speechAllowed = useRef(false);
  const sendVoice = useRef<(text: string) => void>(() => undefined);
  const audio = useAssistantAudio(useCallback((text: string) => sendVoice.current(text), []));
  const speak = audio.speak;
  const answer = useCallback((text: string) => { if (voiceReply && speechAllowed.current) void speak(text); }, [voiceReply, speak]);
  const newImage = useCallback((image: Asset) => { setImages((current) => [...current.filter((item) => item.id !== image.id), image]); setActiveImage((current) => current || image); }, []);
  const assistant = useAssistant(answer, newImage);
  const send = assistant.send;
  useEffect(() => { speechAllowed.current = Boolean(assistant.status?.speech_configured); }, [assistant.status?.speech_configured]);
  const signedIn = assistant.access === "ready";
  const accountKey = assistant.status?.account_id || (signedIn ? "signed-in" : "public");
  const [workspaceAccount, setWorkspaceAccount] = useState(accountKey);
  if (workspaceAccount !== accountKey) {
    setWorkspaceAccount(accountKey); setImages([]); setActiveImage(null); setDrawer(null);
  }
  const ready = signedIn && Boolean(assistant.status?.configured);
  const listening = audio.microphone.status === "listening";
  const requesting = audio.microphone.status === "requesting";
  const phase = listening ? "listening" : audio.speaking ? "speaking" : assistant.busy || audio.transcribing || audio.preparing ? "thinking" : "idle";
  const presentation = useRef<VisualState>({ phase: "idle", reply: false, reveal: 0, revealWidth: 600, revealHeight: 370 });
  const level = useRef(0);
  const voiceControl = useRef<HTMLDivElement>(null);
  useEffect(() => { sendVoice.current = (text) => { void send(text); }; }, [send]);
  useEffect(() => {
    presentation.current.phase = phase;
    presentation.current.reply = phase === "speaking" || audio.preparing || (assistant.busy && assistant.messages.some((message) => message.streaming && message.text.length > 0));
  }, [phase, audio.preparing, assistant.busy, assistant.messages]);
  useEffect(() => {
    let frame = 0;
    const paint = () => {
      level.current = listening ? audio.microphone.levelRef.current : audio.speaking ? audio.playbackLevel.current : 0;
      voiceControl.current?.style.setProperty("--voice-level", String(level.current));
      frame = requestAnimationFrame(paint);
    };
    frame = requestAnimationFrame(paint); return () => cancelAnimationFrame(frame);
  }, [listening, audio.speaking, audio.microphone.levelRef, audio.playbackLevel]);
  const closeDrawer = useCallback(() => setDrawer(null), []);
  const closeImage = useCallback(() => setActiveImage(null), []);
  const openImage = useCallback((image: Asset, collection?: Asset[]) => { if (collection) setImages(collection); else setImages((current) => current.some((item) => item.id === image.id) ? current : [...current, image]); setActiveImage(image); }, []);
  const newConversation = () => { audio.stopInput(true); audio.stopPlayback(); assistant.newConversation(); setActiveImage(null); setImages([]); };
  const label = phase === "listening" ? "Listening to you" : phase === "speaking" ? "Your answer, taking shape" : audio.preparing ? "Preparing your spoken reply" : phase === "thinking" ? assistant.progress || "A moment of thought" : ready ? "Your workspace. Just ask." : "A little closer to every journey.";

  return <main className={styles.page} data-phase={phase} data-has-conversation={assistant.messages.length > 0} data-image-open={Boolean(activeImage)}>
    <div className={styles.atmosphere} aria-hidden="true">{MOTES.map((mote, index) => <i key={index} className={index % 5 === 0 ? styles.doubleMote : undefined} style={{ left: mote.left, top: mote.top, animationDelay: mote.delay, animationDuration: mote.duration, width: mote.size, height: mote.size }} />)}</div>
    <header className={styles.header}>
      <div className={styles.brand} aria-label="Global Connects"><span className={styles.monogram}>gc<ArrowUpRight size={16} strokeWidth={2.5} /></span><span>Global Connects<small>YOUR TRAVEL WORKSPACE</small></span></div>
      <div className={styles.headerActions}><span className={styles.connection} data-connected={signedIn && Boolean(assistant.observedAt)} title={assistant.observedAt ? `Last checked ${new Date(assistant.observedAt).toLocaleTimeString()}` : "Sign in to connect your workspace"}><span />{signedIn && assistant.observedAt ? "Workspace connected" : "Global Connects AI"}</span>
        <button type="button" className={styles.iconButton} onClick={() => setDrawer("library")} aria-label="Open library"><Library size={18} /></button>
        <button type="button" className={styles.iconButton} onClick={() => setDrawer("history")} aria-label="Open conversations"><MessageSquare size={18} /></button>
        <button type="button" className={styles.iconButton} onClick={newConversation} aria-label="New conversation" disabled={assistant.busy}><Plus size={20} /></button>
      </div>
    </header>

    <div className={styles.mainArea}>
      <section className={styles.visualArea} aria-labelledby="assistant-heading">
        <div className={styles.introduction}><p className={styles.eyebrow}>GLOBAL CONNECTS INTELLIGENCE</p><h1 id="assistant-heading">Every journey,<br /><em>a little clearer.</em></h1><p className={styles.subtitle}>Your people, documents and travel plans.<br className={styles.mobileBreak} /> Together in one conversation.</p></div>
        <div className={styles.sculptureStage} data-testid="assistant-stage"><LiquidSculptureHero levelRef={level} presentationRef={presentation} />{signedIn ? <ImageReveal asset={activeImage} images={images} presentationRef={presentation} onSelect={setActiveImage} onClosed={closeImage} /> : null}</div>
        <div className={styles.voiceStatus} ref={voiceControl} data-listening={listening} data-testid="assistant-voice-status">
          <div className={styles.voiceActivity} aria-hidden="true">{[0, 1, 2, 3, 4].map((value) => <span key={value} style={{ height: `calc(3px + var(--voice-level, 0) * ${value % 2 ? 19 : 11}px)` }} />)}</div>
          <p role="status" aria-live="polite">{label}</p>
          {audio.speaking ? <button type="button" onClick={audio.stopPlayback} className={styles.quietButton}><VolumeX size={12} />Stop speaking</button> : <span className={styles.modelBadge}>GPT-6 LUNA <span /> HIGH REASONING</span>}
        </div>
        {!assistant.messages.length ? <div className={styles.suggestions} aria-label="Suggested questions">{SUGGESTIONS.map((question) => <button type="button" key={question} onClick={() => setDraft(question)}>{question}<ArrowUpRight size={13} /></button>)}</div> : null}
      </section>
      {assistant.messages.length ? <ConversationThread messages={assistant.messages} progress={assistant.progress} speaking={audio.speaking} speechReady={Boolean(assistant.status?.speech_configured)} onSpeak={(text) => { audio.warmAudio(); void audio.speak(text); }} onImage={openImage} hasEarlier={Boolean(assistant.olderCursor)} loadingHistory={assistant.loadingHistory} onLoadEarlier={() => void assistant.loadEarlier()} /> : null}
    </div>

    <div className={styles.composerDock}>
      {assistant.access !== "loading" && !ready ? <div className={styles.connectionNotice}>
        {assistant.access === "guest" || assistant.access === "denied" ? <><LogIn size={14} /><span>{assistant.access === "denied" ? "Administrator access is needed for this workspace." : "Sign in to ask about your Global Connects workspace."}</span><a href="/session-restore?from=%2Fai">Sign in<ArrowUpRight size={12} /></a></> : assistant.access === "offline" ? <><RefreshCw size={13} /><span>Your workspace connection is unavailable.</span><button type="button" onClick={() => void assistant.refresh()}>Try again</button></> : <><AudioLines size={14} /><span>Your assistant is being connected. You can explore the voice sculpture.</span></>}
      </div> : null}
      {audio.error || assistant.error ? <div className={styles.errorNotice} role="alert"><span>{audio.error || assistant.error}</span><button type="button" onClick={() => { assistant.setError(""); audio.clearError(); }} aria-label="Dismiss notice"><X size={13} /></button></div> : null}
      <AssistantComposer ready={ready} busy={assistant.busy} listening={listening} requesting={requesting} transcribing={audio.transcribing} text={draft} onTextChange={setDraft} onSubmit={(text, files, mode, count) => { void assistant.send(text, files, mode, count); }} onMic={() => listening || requesting ? audio.stopInput() : void audio.startInput(ready)} onStop={assistant.stop} onWarmAudio={audio.warmAudio} onError={assistant.setError} />
      <div className={styles.bottomMeta}><span>Built around your world of travel.</span><button type="button" disabled={!assistant.status?.speech_configured} onClick={() => { audio.stopPlayback(); setVoiceReply((value) => !value); }} aria-pressed={voiceReply} aria-label={voiceReply ? "Turn off spoken replies" : "Turn on spoken replies"}>{voiceReply ? <Volume2 size={12} /> : <VolumeX size={12} />}{assistant.status?.speech_configured ? "AI voice replies" : "Voice replies coming soon"}</button></div>
    </div>
    {drawer ? <WorkspaceDrawer key={drawer} kind={drawer} signedIn={signedIn} onClose={closeDrawer} onImage={openImage} onConversation={(id) => { audio.stopPlayback(); void assistant.openConversation(id); }} onNew={newConversation} /> : null}
  </main>;
}
