import { isAxiosError } from "axios";

/** The API interceptor returns plain errors; raw Axios errors remain supported. */
export function apiErrorStatus(error: unknown): number | undefined {
  if (typeof error === "object" && error !== null && "status" in error
    && typeof error.status === "number") return error.status;
  return isAxiosError(error) ? error.response?.status : undefined;
}

export function apiErrorCode(error: unknown): string | undefined {
  if (typeof error === "object" && error !== null && "code" in error
    && typeof error.code === "string") return error.code;
  return undefined;
}
