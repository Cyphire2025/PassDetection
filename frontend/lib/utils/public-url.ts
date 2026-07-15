export interface PassportUploadTarget {
  key: "public";
  label: "Public";
  description: string;
  url: string;
}

const DEFAULT_PUBLIC_APP_URL = "https://pass.cyphire.in";

/**
 * Returns the application's current public URL. In the browser, the active
 * origin is authoritative: this keeps local links on localhost and deployed
 * links on the domain that served the application.
 */
export function getPublicAppUrl(): string {
  const browserOrigin = getBrowserOrigin();
  if (browserOrigin) {
    return browserOrigin;
  }

  const configuredUrl = normalizeOrigin(process.env.NEXT_PUBLIC_APP_URL);
  if (configuredUrl && isPublicOrigin(configuredUrl)) {
    return configuredUrl;
  }

  return DEFAULT_PUBLIC_APP_URL;
}

export function getLocalAppUrl(): string {
  const browserOrigin = getBrowserOrigin();
  if (browserOrigin) {
    const url = new URL(browserOrigin);
    return buildOrigin(url.protocol, "localhost", url.port);
  }

  const lanOrigin = getLanAppUrl();
  if (lanOrigin) {
    const url = new URL(lanOrigin);
    return buildOrigin(url.protocol, "localhost", url.port);
  }

  return "http://localhost";
}

export function getLanAppUrl(): string | null {
  const configuredUrl = normalizeOrigin(process.env.NEXT_PUBLIC_APP_URL);
  if (configuredUrl) {
    const configured = new URL(configuredUrl);
    if (!isLocalHostname(configured.hostname)) {
      return configuredUrl;
    }
  }

  const configuredLocalDevUrl = normalizeOrigin(process.env.NEXT_PUBLIC_DEV_APP_URL);
  if (configuredLocalDevUrl) {
    const configured = new URL(configuredLocalDevUrl);
    if (!isLocalHostname(configured.hostname)) {
      return configuredLocalDevUrl;
    }
  }

  const browserOrigin = getBrowserOrigin();
  if (!browserOrigin) return null;

  const browserUrl = new URL(browserOrigin);
  return isLocalHostname(browserUrl.hostname) ? null : browserOrigin;
}

export function getPassportUploadTargets(token: string): PassportUploadTarget[] {
  const path = `/upload/${encodeURIComponent(token)}`;
  return [
    {
      key: "public",
      label: "Public",
      description: "Share this with clients on any phone or browser.",
      url: `${getPublicAppUrl()}${path}`,
    },
  ];
}

export function getPassportUploadUrl(token: string): string {
  return getPassportUploadTargets(token)[0]?.url ?? `${getPublicAppUrl()}/upload/${encodeURIComponent(token)}`;
}

function getBrowserOrigin(): string | null {
  if (typeof window === "undefined") return null;
  return normalizeOrigin(window.location.origin);
}

function normalizeOrigin(url: string | undefined | null): string | null {
  const value = url?.trim();
  if (!value) return null;
  return value.replace(/\/$/, "");
}

function buildOrigin(protocol: string, hostname: string, port: string): string {
  return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
}

function isLocalHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function isPublicOrigin(origin: string): boolean {
  try {
    const { hostname } = new URL(origin);
    return !isLocalHostname(hostname) && !isPrivateNetworkHostname(hostname);
  } catch {
    return false;
  }
}

function isPrivateNetworkHostname(hostname: string): boolean {
  if (
    hostname.endsWith(".local") ||
    hostname.startsWith("10.") ||
    hostname.startsWith("192.168.")
  ) {
    return true;
  }

  const match = /^172\.(\d{1,3})\./.exec(hostname);
  if (!match) return false;

  const secondOctet = Number(match[1]);
  return secondOctet >= 16 && secondOctet <= 31;
}
