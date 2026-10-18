"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { assistantApi } from "../api";
import { rememberLauncher } from "../navigation";
import { AssistantOrb } from "./assistant-orb";
import styles from "./launcher.module.css";

export function AssistantLauncher() {
  const user = useAuthStore(selectUser);
  const sessionVersion = useAuthStore((state) => state.sessionVersion);
  const pathname = usePathname();
  const router = useRouter();
  const [allowed, setAllowed] = useState(false);
  const sequence = useRef(0);
  const account = `${user?.id}:${user?.role}:${user?.agency_id}:${sessionVersion}`;
  const [confirmedAccount, setConfirmedAccount] = useState(account);
  if (confirmedAccount !== account) { setConfirmedAccount(account); setAllowed(false); }
  useEffect(() => {
    if (!user) return;
    const abort = new AbortController();
    const current = ++sequence.current;
    const check = () => { void assistantApi.availability(abort.signal).then((value) => {
      if (!abort.signal.aborted && current === sequence.current) setAllowed(value.enabled && value.allowed);
    }).catch(() => { if (!abort.signal.aborted && current === sequence.current) setAllowed(false); }); };
    check();
    const timer = setInterval(() => { if (!document.hidden) check(); }, 30000);
    window.addEventListener("assistant-settings-changed", check);
    return () => { abort.abort(); clearInterval(timer); window.removeEventListener("assistant-settings-changed", check); };
  }, [user?.id, user?.role, user?.agency_id, sessionVersion, user]);
  const preload = useCallback(() => { router.prefetch("/ai"); const image = new window.Image(); image.src = "/ai/liquid-sculpture.webp"; }, [router]);
  if (!user || !allowed) return null;
  return <button type="button" className={styles.launcher} aria-label="Open Global Connects AI" title="Global Connects AI" data-assistant-launcher
    onPointerEnter={preload} onFocus={preload} onClick={(event) => { rememberLauncher(event.currentTarget); router.push("/ai", { scroll: false }); }}><AssistantOrb animated={pathname !== "/ai"} /></button>;
}
