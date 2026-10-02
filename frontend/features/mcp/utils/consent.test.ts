import { expect, it } from "vitest";
import type { McpOverview } from "../api/mcp.api";
import { parseMcpAuthorization, validatedMcpRedirect } from "./consent";

const overview: McpOverview = {
  read_only_mode: false,
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

const directOverview: McpOverview = { ...overview, approved_clients: {}, direct_clients: {
  "https://chatgpt.com/oauth/codex/client.json": ["http://127.0.0.1/callback"],
  "https://chatgpt.com/oauth/client.json": ["https://chatgpt.com/connector_platform_oauth_redirect"],
} };
it.each([49153, 63000])("accepts the published Codex loopback callback on native port %s", (port) => {
  expect(parseMcpAuthorization({ ...parameters, client_id: "https://chatgpt.com/oauth/codex/client.json",
    redirect_uri: `http://127.0.0.1:${port}/callback` }, directOverview)).not.toBeNull();
});
it.each([
  "http://localhost:49153/callback", "http://127.0.0.2:49153/callback", "http://127.0.0.1:49153/other",
  "http://127.0.0.1:49153/callback?forward=evil", "http://user@127.0.0.1:49153/callback", "https://127.0.0.1:49153/callback",
])("rejects unpublished native callback authority %s", (redirect_uri) => {
  expect(parseMcpAuthorization({ ...parameters, client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri }, directOverview)).toBeNull();
});
it("requires exact HTTPS ChatGPT callback and does not permit port substitution", () => {
  const client_id = "https://chatgpt.com/oauth/client.json";
  const redirect_uri = "https://chatgpt.com/connector_platform_oauth_redirect";
  expect(parseMcpAuthorization({ ...parameters, client_id, redirect_uri }, directOverview)).not.toBeNull();
  for (const target of [redirect_uri.replace("chatgpt.com", "chatgpt.com.evil.test"), redirect_uri.replace("chatgpt.com", "chatgpt.com:444"), `${redirect_uri}/other`]) {
    expect(parseMcpAuthorization({ ...parameters, client_id, redirect_uri: target }, directOverview)).toBeNull();
  }
});
it("does not substitute the port of a fixed legacy callback", () => {
  expect(parseMcpAuthorization({ ...parameters, redirect_uri: "http://127.0.0.1:49153/callback" }, overview)).toBeNull();
});
it("validates a single issuer in the callback without letting it expand the return destination", () => {
  const request = parseMcpAuthorization(parameters, overview)!;
  const valid = `${request.redirect_uri}?${new URLSearchParams({ code: "one-use", state: request.state, iss: new URL(request.resource).origin })}`;
  expect(validatedMcpRedirect(valid, request)).toBe(valid);
  for (const bad of [valid.replace("app.example.test", "evil.test"), `${valid}&iss=https%3A%2F%2Fapp.example.test`, `${valid}&next=https://evil.test`]) {
    expect(() => validatedMcpRedirect(bad, request)).toThrow();
  }
});
it("requires issuer identification for native app callbacks while accepting the matching origin", () => {
  const request = parseMcpAuthorization({ ...parameters, client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: "http://127.0.0.1:49153/callback" }, directOverview)!;
  const withoutIssuer = `${request.redirect_uri}?${new URLSearchParams({ code: "one-use", state: request.state })}`;
  expect(() => validatedMcpRedirect(withoutIssuer, request)).toThrow();
  expect(validatedMcpRedirect(`${withoutIssuer}&${new URLSearchParams({ iss: new URL(request.resource).origin })}`, request)).toContain("iss=");
});
