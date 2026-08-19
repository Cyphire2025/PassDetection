const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HOST_LABEL_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i;
const IDENTIFIER_PATTERN = /^[a-z0-9][a-z0-9._-]{5,127}$/i;

export const PROFILE_STAGES = Object.freeze({
  smoke: Object.freeze([
    Object.freeze({ duration: "15s", target: 10 }),
    Object.freeze({ duration: "2m", target: 10 }),
    Object.freeze({ duration: "15s", target: 0 }),
  ]),
  "1k": Object.freeze([
    Object.freeze({ duration: "5m", target: 1000 }),
    Object.freeze({ duration: "60m", target: 1000 }),
    Object.freeze({ duration: "5m", target: 0 }),
  ]),
  "5k": Object.freeze([
    Object.freeze({ duration: "5m", target: 1000 }),
    Object.freeze({ duration: "10m", target: 5000 }),
    Object.freeze({ duration: "60m", target: 5000 }),
    Object.freeze({ duration: "10m", target: 0 }),
  ]),
  "10k": Object.freeze([
    Object.freeze({ duration: "5m", target: 1000 }),
    Object.freeze({ duration: "10m", target: 5000 }),
    Object.freeze({ duration: "10m", target: 10000 }),
    Object.freeze({ duration: "60m", target: 10000 }),
    Object.freeze({ duration: "10m", target: 0 }),
  ]),
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

export function stagesForProfile(profile) {
  const source = PROFILE_STAGES[profile];
  if (!source) {
    throw new Error("MOBILE_LOAD_PROFILE must be smoke, 1k, 5k, or 10k");
  }
  return source.map((stage) => ({ duration: stage.duration, target: stage.target }));
}

export function maximumVus(stages) {
  if (!Array.isArray(stages) || stages.length === 0) {
    throw new Error("At least one load stage is required");
  }
  return Math.max(...stages.map((stage) => stage.target));
}

export function validateLoadEnvironment(environment) {
  if (environment.LOAD_TEST_APPROVED !== "true") {
    throw new Error("Set LOAD_TEST_APPROVED=true only after the staging run is authorized");
  }
  if (environment.LOAD_TEST_TARGET_ENVIRONMENT !== "staging") {
    throw new Error("LOAD_TEST_TARGET_ENVIRONMENT must be exactly staging");
  }

  const stagingOrigin = normalizeHttpsOrigin(
    environment.LOAD_TEST_EXPECTED_ORIGIN,
    "LOAD_TEST_EXPECTED_ORIGIN",
  );
  const productionOrigin = normalizeHttpsOrigin(
    environment.LOAD_TEST_PRODUCTION_ORIGIN,
    "LOAD_TEST_PRODUCTION_ORIGIN",
  );
  if (stagingOrigin === productionOrigin) {
    throw new Error("The staging and production origins must be different");
  }

  const rawBaseUrl = requiredText(environment.BASE_URL, "BASE_URL").replace(/\/$/, "");
  const expectedBaseUrl = `${stagingOrigin}/api/v1`;
  const baseSuffix = "/api/v1";
  const suppliedBaseOrigin = rawBaseUrl.endsWith(baseSuffix)
    ? normalizeHttpsOrigin(rawBaseUrl.slice(0, -baseSuffix.length), "BASE_URL")
    : undefined;
  if (suppliedBaseOrigin !== stagingOrigin) {
    throw new Error("BASE_URL must exactly match LOAD_TEST_EXPECTED_ORIGIN plus /api/v1");
  }

  const runId = requiredText(environment.LOAD_TEST_ID, "LOAD_TEST_ID");
  if (!IDENTIFIER_PATTERN.test(runId)) {
    throw new Error("LOAD_TEST_ID must be a 6-128 character operational identifier");
  }
  const approvalReference = requiredText(
    environment.LOAD_TEST_APPROVAL_REFERENCE,
    "LOAD_TEST_APPROVAL_REFERENCE",
  );
  if (!IDENTIFIER_PATTERN.test(approvalReference)) {
    throw new Error(
      "LOAD_TEST_APPROVAL_REFERENCE must be a 6-128 character ticket or change identifier",
    );
  }

  const profile = requiredText(environment.MOBILE_LOAD_PROFILE || "smoke", "MOBILE_LOAD_PROFILE");
  stagesForProfile(profile);
  return Object.freeze({
    approvalReference,
    baseUrl: expectedBaseUrl,
    profile,
    productionOrigin,
    runId,
    stagingOrigin,
  });
}

export function validateCredentialEntries(parsed, requiredCount) {
  if (!Number.isSafeInteger(requiredCount) || requiredCount < 1) {
    throw new Error("The required credential count is invalid");
  }
  if (!Array.isArray(parsed)) {
    throw new Error("MOBILE_LOAD_DATA must contain a JSON array");
  }
  if (parsed.length < requiredCount) {
    throw new Error(`MOBILE_LOAD_DATA needs at least ${requiredCount} unique active sessions`);
  }

  const seenTokens = new Set();
  return parsed.map((entry, index) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
      throw new Error(`MOBILE_LOAD_DATA entry ${index} is invalid`);
    }
    const accessToken = entry.access_token;
    const tripId = entry.trip_id;
    const cursor = entry.cursor === undefined ? 0 : entry.cursor;
    const rawAuthorizedTripIds = entry.authorized_trip_ids === undefined
      ? [tripId]
      : entry.authorized_trip_ids;
    if (
      typeof accessToken !== "string"
      || accessToken.length < 32
      || accessToken.length > 8192
      || accessToken !== accessToken.trim()
      || /\s/.test(accessToken)
      || typeof tripId !== "string"
      || !UUID_PATTERN.test(tripId)
      || !Array.isArray(rawAuthorizedTripIds)
      || rawAuthorizedTripIds.length < 1
      || rawAuthorizedTripIds.length > 500
      || !Number.isSafeInteger(cursor)
      || cursor < 0
    ) {
      throw new Error(`MOBILE_LOAD_DATA entry ${index} is invalid`);
    }
    if (seenTokens.has(accessToken)) {
      throw new Error(
        `MOBILE_LOAD_DATA entry ${index} reuses an access token; every VU needs a unique session`,
      );
    }
    seenTokens.add(accessToken);
    const tripIds = rawAuthorizedTripIds.map((candidate) => {
      if (typeof candidate !== "string" || !UUID_PATTERN.test(candidate)) {
        throw new Error(`MOBILE_LOAD_DATA entry ${index} has an invalid authorized trip`);
      }
      return candidate.toLowerCase();
    });
    if (new Set(tripIds).size !== tripIds.length || !tripIds.includes(tripId.toLowerCase())) {
      throw new Error(
        `MOBILE_LOAD_DATA entry ${index} must list unique authorized trips including trip_id`,
      );
    }
    return Object.freeze({
      accessToken,
      cursor,
      tripId: tripId.toLowerCase(),
      tripIds: Object.freeze(tripIds),
    });
  });
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
