"use client";

import { useCallback, useLayoutEffect, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { animateWorkspace } from "../navigation";
import { AssistantWorkspace } from "./assistant-workspace";
import styles from "./launcher.module.css";

export function AssistantOverlay() {
  const dialog = useRef<HTMLDialogElement>(null);
  const closing = useRef(false);
  const animation = useRef<Animation | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  useLayoutEffect(() => {
    const element = dialog.current;
    if (!element || pathname !== "/ai") return;
    closing.current = false;
    if (!element.open) element.showModal();
    animation.current = animateWorkspace(element, false);
    const active = animation.current;
    void active?.finished.then(() => { if (animation.current === active) { active.cancel(); animation.current = null; } }).catch(() => undefined);
    return () => { animation.current?.cancel(); if (element.open) element.close(); };
  }, [pathname]);
  const close = useCallback(async () => {
    if (closing.current || !dialog.current) return;
    closing.current = true;
    animation.current?.cancel();
    animation.current = animateWorkspace(dialog.current, true);
    await animation.current?.finished.catch(() => undefined);
    router.back();
  }, [router]);
  return pathname !== "/ai" ? null : <dialog ref={dialog} className={styles.overlay} aria-label="Global Connects AI workspace" data-testid="assistant-overlay"
    onCancel={(event) => { event.preventDefault(); window.dispatchEvent(new Event("assistant-request-back")); }}><AssistantWorkspace onBack={() => void close()} /></dialog>;
}
