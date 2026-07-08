"use client";

import { useEffect } from "react";

export function PwaRegistrar() {
  useEffect(() => {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;

    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.warn("PWA service worker registration failed", error);
    });
  }, []);

  return null;
}
