export type StructuredApiErrorDetail = Readonly<{
  code: string;
  message: string;
  details?: Record<string, unknown>;
}>;

export function normalizeStructuredApiErrorDetail(
  value: unknown,
): StructuredApiErrorDetail | null {
  if (!isRecord(value) || typeof value.code !== "string" || typeof value.message !== "string") {
    return null;
  }
  const { code, message, ...metadata } = value;
  return {
    code,
    message,
    ...(Object.keys(metadata).length === 0 ? {} : { details: metadata }),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
