import { expect, it } from "vitest";
import type { McpOverview } from "../api/mcp.api";
import { parseMcpAuthorization, validatedMcpRedirect } from "./consent";

const overview: McpOverview = {
  enabled: true, deployment_enabled: true, emergency_disabled: false,
  resource: "https://app.example.test/mcp", capabilities: ["mcp:read", "mcp:export"],
  approved_clients: { desktop: ["http://127.0.0.1:8765/callback"] },
  environment: "test", revision: "abc", observed_at: "2026-09-29T00:00:00Z", qualification: "in_progress",
};
const parameters = { client_id: "desktop", redirect_uri: "http://127.0.0.1:8765/callback", resource: overview.resource,
  state: "a".repeat(32), code_challenge: "x".repeat(43), code_challenge_method: "S256", response_type: "code", scope: "mcp:read mcp:export" };

it("accepts only the exact approved client resource and requested authority", () => {
  expect(parseMcpAuthorization(parameters, overview)).toMatchObject({ scopes: ["mcp:read", "mcp:export"], redirect_uri: parameters.redirect_uri });
});
it("preserves opaque OAuth state without treating it as markup or a destination", () => {
  const state = "opaque state & symbols / = unicode ✓";
  const request = parseMcpAuthorization({ ...parameters, state }, overview)!;
  expect(request.state).toBe(state);
  const target = `${request.redirect_uri}?code=one-use&${new URLSearchParams({ state })}`;
  expect(validatedMcpRedirect(target, request)).toBe(target);
});
it.each([
  { client_id: "__proto__" }, { client_id: "unapproved" }, { scope: "mcp:delete" }, { scope: "mcp:upload" }, { scope: "" },
  { resource: "https://other.test/mcp" }, { redirect_uri: "http://127.0.0.1:8765/callback/other" },
  { redirect_uri: "javascript:alert(1)" }, { response_type: "token" }, { code_challenge_method: "plain" },
  { code_challenge: "short" }, { state: "short" }, { state: ["a".repeat(32), "b".repeat(32)] },
])("rejects malformed, duplicate or expanded consent parameters %j", (changes) => {
  expect(parseMcpAuthorization({ ...parameters, ...changes }, overview)).toBeNull();
});
it("allows only a single matching state/code callback to the verified destination", () => {
  const request = parseMcpAuthorization(parameters, overview)!;
  const valid = `${request.redirect_uri}?code=opaque-code&state=${request.state}`;
  expect(validatedMcpRedirect(valid, request)).toBe(valid);
  for (const value of [valid.replace("127.0.0.1", "attacker.test"), valid.replace("/callback?", "/other?"),
    `${valid}&state=${request.state}`, `${valid}&code=other`, `${valid}#fragment`, `${valid}&redirect=other`, valid.replace(request.state, "other")]) {
    expect(() => validatedMcpRedirect(value, request)).toThrow();
  }
});
