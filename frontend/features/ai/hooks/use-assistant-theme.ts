"use client";

import { useSyncExternalStore } from "react";

const KEY = "gc.assistant.appearance";
const EVENT = "assistant-appearance-change";
let temporaryChoice: boolean | undefined;

function snapshot() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "dark" || saved === "light") return saved === "dark";
  } catch { /* Private browsing may disallow persistence. */ }
  return temporaryChoice ?? window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function subscribe(listener: () => void) {
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  window.addEventListener(EVENT, listener);
  window.addEventListener("storage", listener);
  media.addEventListener("change", listener);
  return () => {
    window.removeEventListener(EVENT, listener);
    window.removeEventListener("storage", listener);
    media.removeEventListener("change", listener);
  };
}

export function useAssistantTheme() {
  const dark = useSyncExternalStore(subscribe, snapshot, () => false);
  const toggle = () => {
    temporaryChoice = !dark;
    try { localStorage.setItem(KEY, dark ? "light" : "dark"); } catch { /* Keep the session choice. */ }
    window.dispatchEvent(new Event(EVENT));
  };
  return { dark, toggle };
}
