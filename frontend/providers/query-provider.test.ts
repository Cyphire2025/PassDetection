import { describe, expect, it } from "vitest";
import { shouldRetryQuery } from "./query-provider";

describe("shouldRetryQuery", () => {
  it.each([400, 401, 403, 404, 409, 422, 429])(
    "does not amplify an HTTP %s client failure",
    (status) => {
      expect(shouldRetryQuery(0, { code: "TENANT_ACCESS_DENIED", status })).toBe(false);
    },
  );

  it("does not retry structured authentication or rate-limit failures without a status", () => {
    expect(shouldRetryQuery(0, { code: "AUTH_SESSION_EXPIRED" })).toBe(false);
    expect(shouldRetryQuery(0, { code: "REQUEST_RATE_LIMITED" })).toBe(false);
  });

  it("allows at most two attempts for transient network and server failures", () => {
    expect(shouldRetryQuery(0, { code: "NETWORK_ERROR" })).toBe(true);
    expect(shouldRetryQuery(1, { code: "HTTP_503", status: 503 })).toBe(true);
    expect(shouldRetryQuery(2, { code: "HTTP_503", status: 503 })).toBe(false);
  });
});
