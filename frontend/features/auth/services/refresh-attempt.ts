import axios from "axios";

/** A simultaneous rotation may lose the server lock; only that explicit conflict is retryable. */
export async function refreshWithSingleConflictRetry<T>(attempt: () => Promise<T>): Promise<T> {
  try {
    return await attempt();
  } catch (error) {
    if (!axios.isAxiosError<{ error?: { code?: string } }>(error)
      || error.response?.status !== 409
      || error.response.data?.error?.code !== "REFRESH_IN_PROGRESS") throw error;
    await new Promise<void>((resolve) => setTimeout(resolve, 1_000));
    return attempt();
  }
}
