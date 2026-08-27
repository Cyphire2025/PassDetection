const HOST_LABEL_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;
const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9._-]{5,127}$/i;
const REVISION_PATTERN = /^[a-z0-9][a-z0-9._-]{6,127}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const PRINCIPAL_REFERENCE_PATTERN = /^load-vu-[0-9]{3}$/;
const COOKIE_VALUE_PATTERN = /^[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]+$/;
const MAX_SESSION_LIFETIME_SECONDS = 45 * 60;
const MANIFEST_MAXIMUM_AGE_SECONDS = 10 * 60;
const CLOCK_SKEW_SECONDS = 60;
const SESSION_EXPIRY_MARGIN_SECONDS = 2 * 60;

function frozenStages(stages) {
  return Object.freeze(stages.map((stage) => Object.freeze(stage)));
}

export const DASHBOARD_PROFILE_STAGES = Object.freeze({
  load: Object.freeze({
    "100": frozenStages([
      { duration: "2m", target: 100 },
      { duration: "5m", target: 100 },
      { duration: "2m", target: 0 },
    ]),
    "200": frozenStages([
      { duration: "2m", target: 100 },
      { duration: "2m", target: 200 },
      { duration: "5m", target: 200 },
      { duration: "2m", target: 0 },
    ]),
  }),
  soak: Object.freeze({
    "100": frozenStages([
      { duration: "2m", target: 100 },
      { duration: "20m", target: 100 },
      { duration: "2m", target: 0 },
    ]),
    "200": frozenStages([
      { duration: "2m", target: 100 },
      { duration: "2m", target: 200 },
      { duration: "20m", target: 200 },
      { duration: "2m", target: 0 },
    ]),
  }),
});

function frozenThresholds(thresholds) {
  return Object.freeze(Object.fromEntries(
    Object.entries(thresholds).map(([metric, expressions]) => [
      metric,
      Object.freeze([...expressions]),
    ]),
  ));
}

export const DASHBOARD_LOAD_THRESHOLDS = frozenThresholds({
  checks: ["rate>0.995"],
  dashboard_request_success: ["rate>0.995"],
  dashboard_stats_latency: ["p(95)<750", "p(99)<1500"],
  dashboard_notification_feed_latency: ["p(95)<500", "p(99)<1000"],
  dashboard_authorization_failures: ["count==0"],
  dashboard_rate_limited: ["count==0"],
  dashboard_proxy_failures: ["count==0"],
  dashboard_connection_failures: ["count==0"],
  dashboard_contract_failures: ["count==0"],
  dashboard_realtime_connection_success: ["rate>0.995"],
  dashboard_realtime_ready_latency: ["p(95)<1500", "p(99)<3000"],
  dashboard_realtime_protocol_failures: ["count==0"],
  dashboard_realtime_authorization_failures: ["count==0"],
  dashboard_realtime_unexpected_disconnects: ["rate<0.005"],
  dropped_iterations: ["count==0"],
  http_req_failed: ["rate<0.005"],
  http_req_blocked: ["p(95)<250", "p(99)<750"],
  http_req_connecting: ["p(95)<250", "p(99)<750"],
  http_req_tls_handshaking: ["p(95)<500", "p(99)<1000"],
  ws_connecting: ["p(95)<1500", "p(99)<3000"],
});

function requiredText(value, name) {
  if (typeof value !== "string" || value.length === 0 || value !== value.trim()) {
    throw new Error(`${name} must be present without surrounding whitespace`);
  }
  return value;
}

function normalizeHttpsOrigin(value, name) {
  const raw = requiredText(value, name);
  const match = /^https:\/\/([^/?#]+)\/?$/i.exec(raw);
  if (!match) {
    throw new Error(`${name} must be an HTTPS origin without a path, query, or fragment`);
  }
  if (match[1].includes("@") || match[1].includes("[") || match[1].includes("]")) {
    throw new Error(`${name} must use an explicit DNS hostname`);
  }

  const authorityParts = match[1].split(":");
  if (authorityParts.length > 2) {
    throw new Error(`${name} must use an explicit DNS hostname`);
  }
  const hostname = authorityParts[0].toLowerCase();
  const port = authorityParts[1];
  if (
    hostname.length > 253
    || !hostname.includes(".")
    || /^[0-9]+(?:\.[0-9]+){3}$/.test(hostname)
    || hostname.split(".").some((label) => !HOST_LABEL_PATTERN.test(label))
  ) {
    throw new Error(`${name} must use a valid fully qualified DNS hostname`);
  }
  let normalizedPort = "";
  if (port !== undefined) {
    const numericPort = Number(port);
    if (!Number.isSafeInteger(numericPort) || numericPort < 1 || numericPort > 65535) {
      throw new Error(`${name} contains an invalid port`);
    }
    if (numericPort !== 443) normalizedPort = `:${numericPort}`;
  }
  return `https://${hostname}${normalizedPort}`;
}

function normalizeAbsolutePath(value, name) {
  const raw = requiredText(value, name);
  if (raw.includes("\0")) throw new Error(`${name} contains an invalid character`);

  const windowsMatch = /^([a-z]):[\\/](.*)$/i.exec(raw);
  const isPosix = raw.startsWith("/");
  if (!windowsMatch && !isPosix) {
    throw new Error(`${name} must be an absolute local path`);
  }

  const root = windowsMatch ? `${windowsMatch[1].toLowerCase()}:/` : "/";
  const tail = (windowsMatch ? windowsMatch[2] : raw.slice(1)).replace(/\\/g, "/");
  const segments = tail.split("/").filter((segment) => segment.length > 0);
  if (segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`${name} must not contain relative path segments`);
  }
  return segments.length === 0 ? root : `${root}${segments.join("/")}`;
}

function hasExactKeys(value, expectedKeys) {
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function parseIsoTimestamp(value, name) {
  if (typeof value !== "string") throw new Error(`${name} must be an ISO-8601 timestamp`);
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString() !== value) {
    throw new Error(`${name} must use canonical UTC ISO-8601 format`);
  }
  return parsed;
}

function durationSeconds(duration) {
  const match = /^([1-9][0-9]*)(s|m)$/.exec(duration);
  if (!match) throw new Error("A dashboard load stage has an invalid duration");
  return Number(match[1]) * (match[2] === "m" ? 60 : 1);
}

export function stagesForDashboardProfile(profile, mode) {
  const modeProfiles = DASHBOARD_PROFILE_STAGES[mode];
  const source = modeProfiles && modeProfiles[profile];
  if (!source) {
    throw new Error("DASHBOARD_LOAD_PROFILE must be 100 or 200 and DASHBOARD_LOAD_MODE must be load or soak");
  }
  return source.map((stage) => ({ duration: stage.duration, target: stage.target }));
}

export function maximumVus(stages) {
  if (!Array.isArray(stages) || stages.length === 0) {
    throw new Error("At least one dashboard load stage is required");
  }
  return Math.max(...stages.map((stage) => stage.target));
}

export function totalStageDurationSeconds(stages) {
  if (!Array.isArray(stages) || stages.length === 0) {
    throw new Error("At least one dashboard load stage is required");
  }
  return stages.reduce((total, stage) => total + durationSeconds(stage.duration), 0);
}

export function minimumCredentialRemainingSeconds(stages) {
  return totalStageDurationSeconds(stages) + SESSION_EXPIRY_MARGIN_SECONDS;
}

export function validateDashboardLoadEnvironment(environment) {
  if (environment.DASHBOARD_LOAD_APPROVED !== "true") {
    throw new Error(
      "Set DASHBOARD_LOAD_APPROVED=true only after this staging run is authorized",
    );
  }
  if (environment.DASHBOARD_LOAD_TARGET_ENVIRONMENT !== "staging") {
    throw new Error("DASHBOARD_LOAD_TARGET_ENVIRONMENT must be exactly staging");
  }

  const stagingOrigin = normalizeHttpsOrigin(
    environment.DASHBOARD_LOAD_EXPECTED_ORIGIN,
    "DASHBOARD_LOAD_EXPECTED_ORIGIN",
  );
  const productionOrigin = normalizeHttpsOrigin(
    environment.DASHBOARD_LOAD_PRODUCTION_ORIGIN,
    "DASHBOARD_LOAD_PRODUCTION_ORIGIN",
  );
  if (stagingOrigin === productionOrigin) {
    throw new Error("The staging and production origins must be different");
  }

  const rawBaseUrl = requiredText(
    environment.DASHBOARD_BASE_URL,
    "DASHBOARD_BASE_URL",
  ).replace(/\/$/, "");
  const expectedBaseUrl = `${stagingOrigin}/api/v1`;
  if (rawBaseUrl !== expectedBaseUrl) {
    throw new Error(
      "DASHBOARD_BASE_URL must exactly match DASHBOARD_LOAD_EXPECTED_ORIGIN plus /api/v1",
    );
  }

  const runId = requiredText(environment.DASHBOARD_LOAD_RUN_ID, "DASHBOARD_LOAD_RUN_ID");
  if (!IDENTIFIER_PATTERN.test(runId)) {
    throw new Error("DASHBOARD_LOAD_RUN_ID must be a 6-128 character operational identifier");
  }
  const approvalReference = requiredText(
    environment.DASHBOARD_LOAD_APPROVAL_REFERENCE,
    "DASHBOARD_LOAD_APPROVAL_REFERENCE",
  );
  if (!IDENTIFIER_PATTERN.test(approvalReference)) {
    throw new Error(
      "DASHBOARD_LOAD_APPROVAL_REFERENCE must be a 6-128 character ticket or change identifier",
    );
  }
  const expectedRevision = requiredText(
    environment.DASHBOARD_LOAD_EXPECTED_REVISION,
    "DASHBOARD_LOAD_EXPECTED_REVISION",
  );
  if (!REVISION_PATTERN.test(expectedRevision) || expectedRevision === "unknown") {
    throw new Error("DASHBOARD_LOAD_EXPECTED_REVISION must identify the deployed staging revision");
  }

  const profile = requiredText(environment.DASHBOARD_LOAD_PROFILE, "DASHBOARD_LOAD_PROFILE");
  const mode = requiredText(environment.DASHBOARD_LOAD_MODE, "DASHBOARD_LOAD_MODE");
  stagesForDashboardProfile(profile, mode);

  const credentialsSha256 = requiredText(
    environment.DASHBOARD_LOAD_CREDENTIALS_SHA256,
    "DASHBOARD_LOAD_CREDENTIALS_SHA256",
  ).toLowerCase();
  if (!SHA256_PATTERN.test(credentialsSha256)) {
    throw new Error("DASHBOARD_LOAD_CREDENTIALS_SHA256 must be a 64-character SHA-256 digest");
  }

  const repositoryRoot = normalizeAbsolutePath(
    environment.DASHBOARD_LOAD_REPOSITORY_ROOT,
    "DASHBOARD_LOAD_REPOSITORY_ROOT",
  );
  const credentialsPath = normalizeAbsolutePath(
    environment.DASHBOARD_LOAD_CREDENTIALS_PATH,
    "DASHBOARD_LOAD_CREDENTIALS_PATH",
  );
  const expectedManifestName = `dashboard-credentials.${runId}.json`;
  const windowsPath = /^[a-z]:\//i.test(repositoryRoot) && /^[a-z]:\//i.test(credentialsPath);
  const manifestName = credentialsPath.split("/").pop();
  if (
    (windowsPath ? manifestName?.toLowerCase() : manifestName)
    !== (windowsPath ? expectedManifestName.toLowerCase() : expectedManifestName)
  ) {
    throw new Error(
      `DASHBOARD_LOAD_CREDENTIALS_PATH must end with ${expectedManifestName}`,
    );
  }
  const comparableRepositoryRoot = windowsPath ? repositoryRoot.toLowerCase() : repositoryRoot;
  const comparableCredentialsPath = windowsPath ? credentialsPath.toLowerCase() : credentialsPath;
  const repositoryPrefix = comparableRepositoryRoot.endsWith("/")
    ? comparableRepositoryRoot
    : `${comparableRepositoryRoot}/`;
  if (
    comparableCredentialsPath === comparableRepositoryRoot
    || comparableCredentialsPath.startsWith(repositoryPrefix)
  ) {
    throw new Error("DASHBOARD_LOAD_CREDENTIALS_PATH must be outside the repository");
  }

  return Object.freeze({
    approvalReference,
    baseUrl: expectedBaseUrl,
    credentialsPath,
    credentialsSha256,
    expectedRevision,
    mode,
    productionOrigin,
    profile,
    repositoryRoot,
    runId,
    stagingOrigin,
    websocketUrl: `${stagingOrigin.replace(/^https:/i, "wss:")}/api/v1/dashboard/realtime`,
  });
}

export function validateDashboardCredentialManifest(
  parsed,
  { requiredCount, minimumRemainingSeconds, runId, targetOrigin, nowMs = Date.now() },
) {
  if (!Number.isSafeInteger(requiredCount) || requiredCount < 1) {
    throw new Error("The required dashboard credential count is invalid");
  }
  if (!Number.isSafeInteger(minimumRemainingSeconds) || minimumRemainingSeconds < 1) {
    throw new Error("The required dashboard session lifetime is invalid");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("The dashboard credential manifest must be a JSON object");
  }
  if (!hasExactKeys(parsed, [
    "schema_version",
    "run_id",
    "target_origin",
    "generated_at",
    "sessions",
  ])) {
    throw new Error("The dashboard credential manifest has unexpected or missing fields");
  }
  if (parsed.schema_version !== 1 || parsed.run_id !== runId) {
    throw new Error("The dashboard credential manifest does not belong to this run");
  }
  if (normalizeHttpsOrigin(parsed.target_origin, "manifest target_origin") !== targetOrigin) {
    throw new Error("The dashboard credential manifest targets a different origin");
  }

  const generatedAtMs = parseIsoTimestamp(parsed.generated_at, "manifest generated_at");
  if (
    generatedAtMs < nowMs - MANIFEST_MAXIMUM_AGE_SECONDS * 1000
    || generatedAtMs > nowMs + CLOCK_SKEW_SECONDS * 1000
  ) {
    throw new Error("The dashboard credential manifest must be generated within ten minutes of the run");
  }
  if (!Array.isArray(parsed.sessions) || parsed.sessions.length !== requiredCount) {
    throw new Error(
      `The dashboard credential manifest needs exactly ${requiredCount} unique active sessions`,
    );
  }

  const seenPrincipals = new Set();
  const seenCookies = new Set();
  const sessions = parsed.sessions.map((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`Dashboard credential entry ${index} is invalid`);
    }
    if (!hasExactKeys(entry, [
      "principal_ref",
      "session_cookie_value",
      "issued_at",
      "expires_at",
    ])) {
      throw new Error(`Dashboard credential entry ${index} has unexpected or missing fields`);
    }

    const principalRef = entry.principal_ref;
    const sessionCookieValue = entry.session_cookie_value;
    if (typeof principalRef !== "string" || !PRINCIPAL_REFERENCE_PATTERN.test(principalRef)) {
      throw new Error(`Dashboard credential entry ${index} has an invalid synthetic principal reference`);
    }
    if (
      typeof sessionCookieValue !== "string"
      || sessionCookieValue.length < 32
      || sessionCookieValue.length > 8192
      || sessionCookieValue !== sessionCookieValue.trim()
      || !COOKIE_VALUE_PATTERN.test(sessionCookieValue)
    ) {
      throw new Error(`Dashboard credential entry ${index} has an invalid session cookie`);
    }
    if (seenPrincipals.has(principalRef) || seenCookies.has(sessionCookieValue)) {
      throw new Error(
        `Dashboard credential entry ${index} is not unique; every VU needs an isolated session`,
      );
    }

    const issuedAtMs = parseIsoTimestamp(entry.issued_at, `credential entry ${index} issued_at`);
    const expiresAtMs = parseIsoTimestamp(entry.expires_at, `credential entry ${index} expires_at`);
    if (
      issuedAtMs < generatedAtMs - MANIFEST_MAXIMUM_AGE_SECONDS * 1000
      || issuedAtMs > generatedAtMs + CLOCK_SKEW_SECONDS * 1000
      || expiresAtMs <= issuedAtMs
      || expiresAtMs - issuedAtMs > MAX_SESSION_LIFETIME_SECONDS * 1000
    ) {
      throw new Error(`Dashboard credential entry ${index} is not a short-lived run session`);
    }
    if (expiresAtMs < nowMs + minimumRemainingSeconds * 1000) {
      throw new Error(`Dashboard credential entry ${index} expires before the run can finish safely`);
    }

    seenPrincipals.add(principalRef);
    seenCookies.add(sessionCookieValue);
    return Object.freeze({
      expiresAt: entry.expires_at,
      principalRef,
      sessionCookieValue,
    });
  });
  return Object.freeze(sessions);
}

export function boundedIntegerSetting(value, fallback, minimum, maximum, name) {
  if (value === undefined || value === "") return fallback;
  if (!/^[0-9]+$/.test(value)) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}
