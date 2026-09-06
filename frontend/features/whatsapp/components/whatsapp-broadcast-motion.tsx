"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { cn } from "@/lib/utils/cn";
import type { WhatsAppMessageType } from "../api/whatsapp.api";
import styles from "./whatsapp-broadcast-motion.module.css";

export type BroadcastMotionState = "submitting" | "sending" | "complete" | "attention" | "reconnecting";

/** Illustrative dispatch activity. Counts and delivery outcomes belong to the caller. */
export function WhatsAppBroadcastMotion({
  messageType,
  state = "sending",
  compact = false,
  startedAt,
  className,
}: {
  messageType?: WhatsAppMessageType;
  state?: BroadcastMotionState;
  compact?: boolean;
  startedAt?: number;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const root = useRef<HTMLDivElement>(null);
  const [inMotion, setInMotion] = useState(true);

  useLayoutEffect(() => {
    // Rejoining the same batch on another route resumes its six-second cadence.
    // Update only on mount/origin change, never on a progress response.
    const phase = -(Math.max(0, Date.now() - (startedAt ?? 0)) % 6_000) / 1_000;
    root.current?.style.setProperty("--broadcast-phase", `${phase}s`);
  }, [startedAt]);

  useEffect(() => {
    let visible = true;
    const update = () => setInMotion(visible && !document.hidden);
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(
      ([entry]) => { visible = entry.isIntersecting; update(); },
      { threshold: 0 },
    );
    if (root.current) observer?.observe(root.current);
    document.addEventListener("visibilitychange", update);
    update();
    return () => {
      observer?.disconnect();
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  const playing = inMotion && (state === "submitting" || state === "sending");
  return (
    <div
      ref={root}
      aria-hidden="true"
      data-whatsapp-broadcast-motion="true"
      data-state={state}
      data-message-type={messageType ?? "broadcast"}
      data-playing={playing}
      className={cn(styles.scene, compact && styles.compact, className)}
    >
      <svg className={styles.artwork} viewBox="0 0 440 220" fill="none" focusable="false">
        <defs>
          <linearGradient id={`${id}-phone`} x1="166" y1="33" x2="259" y2="192" gradientUnits="userSpaceOnUse">
            <stop stopColor="#237393" /><stop offset="1" stopColor="#0C304C" />
          </linearGradient>
          <linearGradient id={`${id}-glass`} x1="175" y1="44" x2="245" y2="178" gradientUnits="userSpaceOnUse">
            <stop stopColor="#FFFFFF" /><stop offset="1" stopColor="#E5F1F3" />
          </linearGradient>
          <linearGradient id={`${id}-bubble`} x1="191" y1="75" x2="256" y2="127" gradientUnits="userSpaceOnUse">
            <stop stopColor="#B9DF60" /><stop offset="1" stopColor="#98C33B" />
          </linearGradient>
        </defs>

        <ellipse cx="216" cy="200" rx="66" ry="8" fill="#163D55" opacity=".08" />
        <path d="M132 200H301M142 205H159M276 205H290" stroke="#CCDFE6" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="111" cy="32" r="3" fill="#B7D6E1" />
        <circle cx="292" cy="179" r="3" stroke="#B6D55A" strokeWidth="1.5" />
        <path d="M311 27V35M307 31H315M113 170V177M109.5 173.5H116.5" stroke="#BCD0DA" strokeWidth="1.5" strokeLinecap="round" />

        <g className={styles.routes} strokeLinecap="round">
          <path d="M182 83C142 83 138 59 94 59M180 134C140 134 135 160 94 160M257 84C294 84 297 57 336 57M257 132C295 132 300 158 338 158" stroke="#C1D8E1" strokeWidth="1.7" />
          <path className={styles.routeFlow} d="M182 83C142 83 138 59 94 59M180 134C140 134 135 160 94 160M257 84C294 84 297 57 336 57M257 132C295 132 300 158 338 158" stroke="#83B442" strokeWidth="2" strokeDasharray="3 16" />
        </g>

        <Recipient x={18} y={36} delay="0s" />
        <Recipient x={17} y={138} delay="-3s" />
        <Recipient x={335} y={33} delay="-1.5s" />
        <Recipient x={337} y={136} delay="-4.5s" />

        <g className={styles.phone}>
          <g transform="rotate(-7 218 108)">
            <rect x="175" y="27" width="91" height="164" rx="17" fill="#96B2C2" />
            <rect x="170" y="23" width="91" height="164" rx="17" fill={`url(#${id}-phone)`} stroke="#143B55" strokeWidth="2" />
            <rect x="177" y="31" width="77" height="148" rx="11" fill={`url(#${id}-glass)`} />
            <path d="M200 31H232L228 38H204Z" fill="#15435D" />
            <rect x="204" y="171" width="23" height="3" rx="1.5" fill="#92B0BF" />
            <circle cx="191" cy="52" r="6" fill="#1A6383" />
            <path d="M204 50H237M204 56H222" stroke="#AEC8D5" strokeWidth="3" strokeLinecap="round" />
            <path d="M186 65H244" stroke="#D4E4EA" />

            <g className={styles.message}>
              <path d="M198 75H252Q258 75 258 82V117Q258 124 251 124H221L212 131V124H198Q191 124 191 117V82Q191 75 198 75Z" fill={`url(#${id}-bubble)`} stroke="#89B539" strokeWidth="1.5" />
              <MessageMark messageType={messageType} />
              <path d="M204 113H244" stroke="#52792F" strokeOpacity=".45" strokeWidth="2.5" strokeLinecap="round" />
            </g>

            <rect x="185" y="141" width="54" height="16" rx="6" fill="#D5E7ED" />
            <circle className={styles.typingDot} cx="200" cy="149" r="2.5" fill="#568398" />
            <circle className={styles.typingDot} cx="211" cy="149" r="2.5" fill="#568398" style={{ "--dot-delay": "-2s" } as CSSProperties} />
            <circle className={styles.typingDot} cx="222" cy="149" r="2.5" fill="#568398" style={{ "--dot-delay": "-4s" } as CSSProperties} />
          </g>
        </g>

        <g className={styles.packets}>
          <ChatPacket route={styles.northWest} />
          <ChatPacket route={styles.northEast} />
          <ChatPacket route={styles.southWest} />
          <ChatPacket route={styles.southEast} />
        </g>
      </svg>
    </div>
  );
}

function Recipient({ x, y, delay }: { x: number; y: number; delay: string }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect x="2" y="3" width="77" height="46" rx="10" fill="#C9DCE5" opacity=".55" />
      <rect width="77" height="46" rx="10" fill="white" stroke="#B8D1DD" strokeWidth="1.5" />
      <circle cx="19" cy="20" r="10" fill="#E5F0F4" />
      <circle cx="19" cy="17" r="3.8" fill="#719AAD" />
      <path d="M13 26C13 19 25 19 25 26" fill="#719AAD" />
      <path d="M35 15H61M35 22H66M35 29H55" stroke="#B1CBD6" strokeWidth="3" strokeLinecap="round" />
      <path className={styles.recipientHighlight} d="M12 39H65" stroke="#A2C947" strokeWidth="3" strokeLinecap="round" style={{ "--recipient-delay": delay } as CSSProperties} />
    </g>
  );
}

function ChatPacket({ route }: { route: string }) {
  return (
    <g className={cn(styles.packet, route)}>
      <path d="M-7-6H7Q10-6 10-3V4Q10 7 7 7H0L-5 11V7H-7Q-10 7-10 4V-3Q-10-6-7-6Z" fill="#A8D34A" stroke="white" strokeWidth="2" />
      <path d="M-4 0H4" stroke="#476E2E" strokeWidth="1.5" strokeLinecap="round" />
    </g>
  );
}

function MessageMark({ messageType }: { messageType?: WhatsAppMessageType }) {
  if (messageType === "passport_link") {
    return <g transform="translate(209 86)" stroke="#284D39" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5L15 2A6 6 0 0 1 23 10L18 15A6 6 0 0 1 10 15M15 12L12 15M9 12L6 15A6 6 0 0 1-2 7L3 2A6 6 0 0 1 11 2" /></g>;
  }
  if (messageType === "reminder") {
    return <g className={styles.bell} stroke="#284D39" strokeWidth="2.3" strokeLinecap="round" strokeLinejoin="round"><path d="M215 100V92A8 8 0 0 1 231 92V100L234 104H212Z" /><path d="M220 108H226M223 81V83M210 87L208 85M236 87L238 85" /></g>;
  }
  if (messageType === "welcome") {
    return <g stroke="#284D39" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M207 87H239V105H207Z" fill="#CDEB8A" /><path className={styles.greeting} d="M207 87L223 98L239 87" /><path d="M223 79V76M204 82L202 80M242 82L244 80" /></g>;
  }
  return <g stroke="#284D39" strokeWidth="2.5" strokeLinecap="round"><path d="M207 89H238M207 97H232M207 104H224" /></g>;
}
