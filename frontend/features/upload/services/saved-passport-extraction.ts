import type { PassportSubmission } from "@/types/passport.types";
import type { ExtractionWaitResult } from "../components/upload-flow.types";
import { EXTRACTION_POLL_INITIAL_DELAY_MS, EXTRACTION_POLL_WINDOW_MS, isTransientExtractionPollError, nextExtractionPollDelay } from "../components/extraction-polling";
import { canRetryExtractionFor, extractionNoticeFor, isExtractionTerminal, sleep, stageLabel } from "./upload-flow-helpers";

type PollOptions = {
  initial: PassportSubmission;
  signal: AbortSignal;
  fetchStatus: (id: string, signal: AbortSignal) => Promise<PassportSubmission>;
  onProgress: (submission: PassportSubmission, progress: number | null, stage: string) => void;
  now?: () => number;
  wait?: (delay: number, signal: AbortSignal) => Promise<void>;
};

function assertActive(signal: AbortSignal) {
  if (signal.aborted) throw new DOMException("Operation cancelled", "AbortError");
}

function terminalResult(submission: PassportSubmission): ExtractionWaitResult {
  return { submission, notice: extractionNoticeFor(submission), retryAllowed: canRetryExtractionFor(submission) };
}

/** Durable-job polling owns retry/backoff/reconciliation; the caller owns UI state. */
export async function pollSavedPassport({ initial, signal, fetchStatus, onProgress, now = Date.now, wait = sleep }: PollOptions): Promise<ExtractionWaitResult> {
  assertActive(signal);
  let current = initial;
  if (isExtractionTerminal(current)) return terminalResult(current);
  onProgress(current, current.processing_progress ?? 0.05, stageLabel(current.processing_stage ?? current.processing_job_status ?? "queued"));
  const deadline = now() + EXTRACTION_POLL_WINDOW_MS;
  let delayMs = EXTRACTION_POLL_INITIAL_DELAY_MS;
  let consecutiveNetworkFailures = 0;
  while (now() < deadline) {
    await wait(delayMs, signal);
    assertActive(signal);
    try {
      const result = await fetchStatus(current.id, signal);
      assertActive(signal);
      current = result;
      consecutiveNetworkFailures = 0;
    } catch (error) {
      assertActive(signal);
      if (!isTransientExtractionPollError(error)) throw error;
      consecutiveNetworkFailures += 1;
      onProgress(current, current.processing_progress ?? null, "Reconnecting to your saved passport");
      delayMs = nextExtractionPollDelay(delayMs, "failure");
      continue;
    }
    const terminal = isExtractionTerminal(current);
    onProgress(current, terminal ? 1 : current.processing_progress ?? null, stageLabel(current.processing_stage ?? current.processing_job_status ?? "processing"));
    if (terminal) return terminalResult(current);
    delayMs = nextExtractionPollDelay(delayMs, "success");
  }
  assertActive(signal);
  // One boundary read avoids stale empty fields when the worker completed during backoff.
  try {
    current = await fetchStatus(current.id, signal);
    assertActive(signal);
    if (isExtractionTerminal(current)) {
      onProgress(current, 1, stageLabel(current.processing_stage ?? "processing"));
      return terminalResult(current);
    }
  } catch {
    assertActive(signal);
    // The saved upload remains available for manual review when reconciliation fails.
  }
  return {
    submission: current,
    notice: consecutiveNetworkFailures > 0
      ? "Your passport pages are saved. The connection remained unstable while checking the extracted details, so you can continue manually or retry reading the stored image."
      : "Your passport pages are saved. Automatic reading is taking longer than expected, so you can enter the details manually now or retry reading the stored image.",
    retryAllowed: true,
  };
}
