export type ApiRoutingEnvironment = Readonly<{
  NODE_ENV?: string;
  API_BASE_URL?: string;
  NEXT_PUBLIC_API_BASE_URL?: string;
}>;

const DEVELOPMENT_API_BASE = "http://localhost:8000";

/**
 * Next rewrites are a server concern. Production intentionally ignores the
 * public build-time variable: Nginx can keep /api same-origin without baking
 * an internal address into browser JavaScript.
 */
export function resolveApiRewriteBase(environment: ApiRoutingEnvironment): string | null {
  const isProduction = environment.NODE_ENV === "production";
  const configured = nonBlank(environment.API_BASE_URL)
    ?? (isProduction ? null : nonBlank(environment.NEXT_PUBLIC_API_BASE_URL));
  if (configured) return validateApiOrigin(configured);
  return isProduction ? null : DEVELOPMENT_API_BASE;
}

/** Server-side Axios calls may use the internal origin; browsers stay relative. */
export function resolveServerApiBaseUrl(environment: ApiRoutingEnvironment): string {
  const configured = nonBlank(environment.API_BASE_URL)
    ?? (environment.NODE_ENV === "production"
      ? null
      : nonBlank(environment.NEXT_PUBLIC_API_BASE_URL));
  return configured ? validateApiOrigin(configured) : "";
}

export function validateApiOrigin(value: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error("API_BASE_URL must be an absolute HTTP(S) origin");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("API_BASE_URL must use HTTP or HTTPS");
  }
  if (parsed.username || parsed.password) {
    throw new Error("API_BASE_URL must not contain credentials");
  }
  if (parsed.search || parsed.hash || (parsed.pathname !== "/" && parsed.pathname !== "")) {
    throw new Error("API_BASE_URL must be an origin without a path, query, or fragment");
  }
  return parsed.origin;
}

function nonBlank(value: string | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}
