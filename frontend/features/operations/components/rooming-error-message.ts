export function roomingErrorMessage(error: unknown, fallback: string) {
  if (!error || typeof error !== "object" || !("message" in error)) {
    return fallback;
  }

  if (typeof error.message === "string" && error.message) {
    return error.message;
  }

  if (
    error.message
    && typeof error.message === "object"
    && "message" in error.message
    && typeof error.message.message === "string"
    && error.message.message
  ) {
    return error.message.message;
  }

  return fallback;
}
