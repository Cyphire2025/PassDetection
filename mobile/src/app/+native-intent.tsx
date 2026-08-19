const VERIFIED_ACTIVATION_ORIGIN = "https://tech.gctravels.com";
const VERIFIED_ACTIVATION_PATH = "/gc/activate";
const ACTIVATION_TOKEN_PATTERN = /^[A-Za-z0-9_-]{32,512}$/;

export function redirectSystemPath({
  path,
}: {
  path: string;
  initial: boolean;
}): string {
  try {
    // Activation credentials are accepted only from the platform-verified
    // HTTPS origin. A custom URL scheme can be claimed by another installed
    // app and therefore must never carry a bearer credential.
    const url = new URL(path);
    if (
      url.origin !== VERIFIED_ACTIVATION_ORIGIN ||
      url.username !== "" ||
      url.password !== "" ||
      url.pathname !== VERIFIED_ACTIVATION_PATH ||
      url.hash !== ""
    )
      return "/";

    const keys = [...url.searchParams.keys()];
    const tokens = url.searchParams.getAll("token");
    if (keys.length !== 1 || keys[0] !== "token" || tokens.length !== 1)
      return "/";

    const token = tokens[0];
    if (!token || !ACTIVATION_TOKEN_PATTERN.test(token)) return "/";
    return `/activate?token=${encodeURIComponent(token)}`;
  } catch {
    // Malformed external paths are routed to the safe welcome screen.
  }
  return "/";
}
