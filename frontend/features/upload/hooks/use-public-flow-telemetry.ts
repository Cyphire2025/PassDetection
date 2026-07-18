"use client";

import { useCallback, useEffect, useRef } from "react";
import { uploadLinksApi } from "@/features/passports/api/upload-links.api";
import {
  enqueueTelemetry,
  parseTelemetryQueue,
  type PublicFlowReason,
  type PublicFlowTelemetryPayload,
} from "../services/public-flow-telemetry";

const TELEMETRY_QUEUE_STORAGE_KEY = "gct:public-flow-telemetry:v1";

function readQueue() {
  try {
    return parseTelemetryQueue(
      window.sessionStorage.getItem(TELEMETRY_QUEUE_STORAGE_KEY),
    );
  } catch {
    return [];
  }
}

function writeQueue(queue: readonly PublicFlowTelemetryPayload[]) {
  try {
    if (queue.length === 0) {
      window.sessionStorage.removeItem(TELEMETRY_QUEUE_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(
      TELEMETRY_QUEUE_STORAGE_KEY,
      JSON.stringify(queue),
    );
  } catch {
    // Telemetry must never block the public upload flow.
  }
}

function queuePayload(payload: PublicFlowTelemetryPayload) {
  writeQueue(enqueueTelemetry(readQueue(), payload));
}

export function usePublicFlowTelemetry(
  token: string,
  hasActiveProgress: boolean,
) {
  const activeProgressRef = useRef(false);
  const abandonmentReportedRef = useRef(false);
  const offlineRef = useRef(false);
  const onceReasonsRef = useRef(new Set<PublicFlowReason>());
  const flushInFlightRef = useRef<Promise<void> | null>(null);

  useEffect(() => {
    activeProgressRef.current = hasActiveProgress;
    if (!hasActiveProgress) abandonmentReportedRef.current = false;
  }, [hasActiveProgress]);

  const flushQueue = useCallback(() => {
    if (
      typeof navigator !== "undefined"
      && !navigator.onLine
    ) {
      return Promise.resolve();
    }
    if (flushInFlightRef.current) return flushInFlightRef.current;

    const pending = readQueue();
    if (pending.length === 0) return Promise.resolve();

    const task = (async () => {
      for (let index = 0; index < pending.length; index += 1) {
        try {
          await uploadLinksApi.recordTelemetry(token, pending[index]);
        } catch {
          return;
        }
        // Queue writers only append. Removing one acknowledged item at a time
        // preserves anything added by an offline event while this flush runs.
        writeQueue(readQueue().slice(1));
      }
    })().finally(() => {
      if (flushInFlightRef.current === task) {
        flushInFlightRef.current = null;
      }
    });
    flushInFlightRef.current = task;
    return task;
  }, [token]);

  const report = useCallback((
    payload: PublicFlowTelemetryPayload,
  ): Promise<void> => {
    if (
      typeof navigator !== "undefined"
      && !navigator.onLine
    ) {
      queuePayload(payload);
      return Promise.resolve();
    }
    return flushQueue()
      .then(() => uploadLinksApi.recordTelemetry(token, payload))
      .catch(() => {
        queuePayload(payload);
      });
  }, [flushQueue, token]);

  const reportPublicFlowOnce = useCallback((
    reason: PublicFlowReason,
  ) => {
    if (onceReasonsRef.current.has(reason)) return;
    onceReasonsRef.current.add(reason);
    void report({ event: "public_flow", reason });
  }, [report]);

  useEffect(() => {
    offlineRef.current = !navigator.onLine;
    if (offlineRef.current) {
      reportPublicFlowOnce("connectivity_lost");
    } else {
      void flushQueue();
    }

    const handleOffline = () => {
      if (offlineRef.current) return;
      offlineRef.current = true;
      void report({
        event: "public_flow",
        reason: "connectivity_lost",
      });
    };
    const handleOnline = () => {
      if (!offlineRef.current) {
        void flushQueue();
        return;
      }
      offlineRef.current = false;
      void flushQueue().then(() => report({
        event: "public_flow",
        reason: "connectivity_restored",
      }));
    };
    const handlePageHide = (event: PageTransitionEvent) => {
      if (
        event.persisted
        || !activeProgressRef.current
        || abandonmentReportedRef.current
      ) {
        return;
      }
      abandonmentReportedRef.current = true;
      const payload: PublicFlowTelemetryPayload = {
        event: "public_flow",
        reason: "upload_abandoned",
      };
      if (!navigator.onLine) {
        queuePayload(payload);
        return;
      }
      void uploadLinksApi.recordTelemetryKeepalive(token, payload).catch(() => {
        queuePayload(payload);
      });
    };

    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("pagehide", handlePageHide);
    };
  }, [flushQueue, report, reportPublicFlowOnce, token]);

  return {
    report,
    reportPublicFlowOnce,
  };
}
