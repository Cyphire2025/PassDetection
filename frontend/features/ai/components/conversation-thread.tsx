"use client";

import Image from "next/image";
import { ArrowDown, Check, ChevronRight, Copy, FileText, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Asset, Message } from "../types";
import { MessageContent } from "./message-content";
import styles from "./thread.module.css";

export function ConversationThread({ messages, progress, speaking, speechReady, onSpeak, onImage, hasEarlier, loadingHistory, onLoadEarlier, onHide }: {
  messages: Message[]; progress: string; speaking: boolean; speechReady: boolean;
  onSpeak: (text: string) => void; onImage: (asset: Asset) => void;
  hasEarlier: boolean; loadingHistory: boolean; onLoadEarlier: () => void;
  onHide: () => void;
}) {
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const [atEnd, setAtEnd] = useState(true);
  const [copied, setCopied] = useState<string | null>(null);
  useEffect(() => { if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [messages, progress]);
  useEffect(() => { if (!copied) return; const timer = setTimeout(() => setCopied(null), 1800); return () => clearTimeout(timer); }, [copied]);
  const toEnd = () => { follow.current = true; setAtEnd(true); scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: "smooth" }); };
  return <section className={styles.thread} aria-label="Conversation">
    <div className={styles.threadHeader}><span>YOUR CONVERSATION</span><div className={styles.headerActions}><span className={styles.private}>Private workspace</span><button type="button" onClick={onHide} className={styles.hideButton} aria-label="Hide conversation" aria-controls="assistant-conversation-panel" aria-expanded="true" data-conversation-close><ChevronRight size={18} /></button></div></div>
    <div className={styles.messages} ref={scroll} tabIndex={0} onScroll={() => {
      const element = scroll.current; if (!element) return;
      follow.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80; setAtEnd(follow.current);
    }}>
      {hasEarlier ? <button type="button" className={styles.earlier} disabled={loadingHistory} onClick={() => { follow.current = false; onLoadEarlier(); }}>{loadingHistory ? "Loading earlier messages…" : "Load earlier messages"}</button> : null}
      {messages.map((message) => <article key={message.id} className={`${styles.message} ${message.role === "user" ? styles.user : styles.assistant}`}>
        <div className={styles.messageLabel}>{message.role === "user" ? "You" : "Global Connects"}{message.streaming ? <span className={styles.liveDot} aria-label="Responding" /> : null}</div>
        {message.text ? <MessageContent text={message.text} /> : message.streaming ? <div className={styles.thinking}><span /><span /><span /><p>{progress || "Thinking"}</p></div> : null}
        {message.attachments?.length ? <div className={styles.files}>{message.attachments.map((file) => <span key={file.id}><FileText size={13} />{file.name}</span>)}</div> : null}
        {message.images?.length ? <div className={styles.imageGrid}>{message.images.map((asset) => <button type="button" key={asset.id} onClick={() => onImage(asset)} aria-label={`Open ${asset.name}`}><Image src={asset.url} alt={asset.name} width={240} height={160} unoptimized /></button>)}</div> : null}
        {message.sources?.length ? <div className={styles.sources}>{message.sources.filter((source, index, list) => list.findIndex((value) => value.view === source.view) === index).map((source) => <span key={source.view} title={`Checked ${new Date(source.observed_at).toLocaleTimeString()}; ${source.completeness}`}><span />{source.view.replaceAll("_", " ")}</span>)}</div> : null}
        {message.error ? <p className={styles.messageError} role="status">{message.error}</p> : null}
        {message.role === "assistant" && message.text && !message.streaming ? <div className={styles.messageActions}>
          <button type="button" onClick={() => void navigator.clipboard?.writeText(message.text).then(() => setCopied(message.id)).catch(() => undefined)} aria-label={copied === message.id ? "Reply copied" : "Copy reply"}>{copied === message.id ? <Check size={14} /> : <Copy size={14} />}</button>
          {speechReady ? <button type="button" disabled={speaking} onClick={() => onSpeak(message.text)} aria-label="Read reply aloud"><Volume2 size={15} /></button> : null}
        </div> : null}
      </article>)}
    </div>
    {!atEnd ? <button type="button" className={styles.jump} onClick={toEnd} aria-label="Jump to latest reply"><ArrowDown size={15} /></button> : null}
    <div className={styles.screenReader} role="status" aria-live="polite">{progress}</div>
  </section>;
}
