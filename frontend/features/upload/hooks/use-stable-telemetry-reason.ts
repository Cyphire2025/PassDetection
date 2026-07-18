"use client";

import { useEffect, useRef } from "react";
import {
  advanceStableReason,
  createStableReasonState,
  type StableReasonState,
} from "../services/public-flow-telemetry";

export function useStableTelemetryReason<Reason extends string>(
  reason: Reason | null,
  onStableReason: (reason: Reason) => void,
  stableWindowMs = 1_000,
) {
  const stateRef = useRef<StableReasonState<Reason>>(
    createStableReasonState<Reason>(),
  );
  const onStableReasonRef = useRef(onStableReason);

  useEffect(() => {
    onStableReasonRef.current = onStableReason;
  }, [onStableReason]);

  useEffect(() => {
    const now = window.performance.now();
    const advanced = advanceStableReason(
      stateRef.current,
      reason,
      now,
      stableWindowMs,
    );
    stateRef.current = advanced.state;
    if (advanced.emittedReason) {
      onStableReasonRef.current(advanced.emittedReason);
      return;
    }
    if (!reason || advanced.state.emitted.includes(reason)) return;

    const elapsed = advanced.state.candidateSinceMs === null
      ? 0
      : now - advanced.state.candidateSinceMs;
    const timer = window.setTimeout(() => {
      const completed = advanceStableReason(
        stateRef.current,
        reason,
        window.performance.now(),
        stableWindowMs,
      );
      stateRef.current = completed.state;
      if (completed.emittedReason) {
        onStableReasonRef.current(completed.emittedReason);
      }
    }, Math.max(0, stableWindowMs - elapsed));
    return () => window.clearTimeout(timer);
  }, [reason, stableWindowMs]);
}
