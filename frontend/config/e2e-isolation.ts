export const E2E_APP_PORT = 3_100;
export const E2E_REALTIME_STUB_PORT = 3_199;
export const E2E_API_ORIGIN = `http://127.0.0.1:${E2E_REALTIME_STUB_PORT}`;

type InheritedEnvironment = Readonly<Record<string, string | undefined>>;

/**
 * Playwright must never inherit a developer or production API destination.
 * Explicit process values take precedence over Next's .env.local loading, so
 * every HTTP rewrite and WebSocket upgrade remains inside the test harness.
 */
export function isolatedE2eProcessEnvironment(
  inherited: InheritedEnvironment,
): Record<string, string> {
  const definedEnvironment = Object.fromEntries(
    Object.entries(inherited).filter(
      (entry): entry is [string, string] => typeof entry[1] === "string",
    ),
  );
  return {
    ...definedEnvironment,
    API_BASE_URL: E2E_API_ORIGIN,
    NEXT_PUBLIC_API_BASE_URL: E2E_API_ORIGIN,
  };
}
