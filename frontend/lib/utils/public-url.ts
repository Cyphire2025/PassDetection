export interface PassportUploadTarget {
  key: "local" | "lan";
  label: "Local" | "LAN";
  description: string;
  url: string;
}

/**
 * Returns the externally shareable application URL.
 * Configure NEXT_PUBLIC_APP_URL for LAN or production deployments; the
 * browser origin remains a safe fallback for ordinary local development.
 */
export function getPublicAppUrl(): string {
  return getLanAppUrl() ?? getBrowserOrigin() ?? "http://localhost";
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

  const browserOrigin = getBrowserOrigin();
  if (!browserOrigin) return null;

  const browserUrl = new URL(browserOrigin);
  return isLocalHostname(browserUrl.hostname) ? null : browserOrigin;
}

export function getPassportUploadTargets(token: string): PassportUploadTarget[] {
  const path = `/upload/${encodeURIComponent(token)}`;
  const targets: PassportUploadTarget[] = [
    {
      key: "local",
      label: "Local",
      description: "Use on the same laptop or desktop.",
      url: `${getLocalAppUrl()}${path}`,
    },
  ];

  const lanOrigin = getLanAppUrl();
  if (lanOrigin) {
    const lanUrl = `${lanOrigin}${path}`;
    if (lanUrl !== targets[0].url) {
      targets.push({
        key: "lan",
        label: "LAN",
        description: "Use from phones or other devices on the same Wi-Fi.",
        url: lanUrl,
      });
    }
  }

  return targets;
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
