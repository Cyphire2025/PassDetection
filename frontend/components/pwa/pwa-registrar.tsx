"use client";

import { useEffect } from "react";

export function PwaRegistrar() {
  useEffect(() => {
    if (!("serviceWorker" in navigator) || !window.isSecureContext) return;

    let disposed = false;
    let registration: ServiceWorkerRegistration | null = null;
    let updatePromise: Promise<void> | null = null;

    const update = () => {
      if (!registration || updatePromise) return updatePromise;
      updatePromise = registration
        .update()
        .then(() => {
          registration?.waiting?.postMessage({ type: "SKIP_WAITING" });
        })
        .catch((error) => {
          console.warn("PWA service worker update failed", error);
        })
        .finally(() => {
          updatePromise = null;
        });
      return updatePromise;
    };

    const handleUsable = () => {
      if (document.visibilityState === "visible" && navigator.onLine) {
        void update();
      }
    };

    navigator.serviceWorker
      .register("/sw.js", {
        scope: "/",
        updateViaCache: "none",
      })
      .then((registered) => {
        if (disposed) return;
        registration = registered;
        return update();
      })
      .catch((error) => {
        console.warn("PWA service worker registration failed", error);
      });

    window.addEventListener("online", handleUsable);
    document.addEventListener("visibilitychange", handleUsable);

    return () => {
      disposed = true;
      registration = null;
      window.removeEventListener("online", handleUsable);
      document.removeEventListener("visibilitychange", handleUsable);
    };
  }, []);

  return null;
}
