import { passportsApi, type VisaAiGenerationJob } from "../api/passports.api";

const VISA_AI_JOB_POLL_INTERVAL_MS = 2_000;
const VISA_AI_JOB_POLL_FAILURE_LIMIT = 4;

export async function waitForVisaAiGenerationJob(
  submissionId: string,
  initialJob: VisaAiGenerationJob,
  signal: AbortSignal,
) {
  let job = initialJob;
  let consecutiveFailures = 0;
  while (job.status === "queued" || job.status === "running") {
    await abortableDelay(VISA_AI_JOB_POLL_INTERVAL_MS, signal);
    try {
      job = await passportsApi.getVisaAiGenerationJob(
        submissionId,
        job.id,
        signal,
      );
      consecutiveFailures = 0;
    } catch (pollError) {
      if (signal.aborted) throw pollError;
      consecutiveFailures += 1;
      if (consecutiveFailures >= VISA_AI_JOB_POLL_FAILURE_LIMIT) {
        throw pollError;
      }
    }
  }
  return job;
}

function abortableDelay(milliseconds: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException("Polling stopped.", "AbortError"));
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    }, milliseconds);
    const handleAbort = () => {
      window.clearTimeout(timer);
      reject(new DOMException("Polling stopped.", "AbortError"));
    };
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

