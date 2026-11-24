import { expect, it } from "vitest";
import { validatedMcpRedirect, validatedMcpRequestCallback } from "./consent";
const parameters = { client_id: "desktop", redirect_uri: "http://127.0.0.1:8765/callback", resource: "https://app.example.test/mcp",
  state: "a".repeat(32) };
it("preserves opaque OAuth state without treating it as markup or a destination", () => {
  const state = "opaque state & symbols / = unicode ✓";
  const request = { ...parameters, state };
  expect(request.state).toBe(state);
  const target = `${request.redirect_uri}?code=one-use&${new URLSearchParams({ state })}`;
  expect(validatedMcpRedirect(target, request)).toBe(target);
});
it("allows only a single matching state/code callback to the verified destination", () => {
  const request = parameters;
  const valid = `${request.redirect_uri}?code=opaque-code&state=${request.state}`;
  expect(validatedMcpRedirect(valid, request)).toBe(valid);
  for (const value of [valid.replace("127.0.0.1", "attacker.test"), valid.replace("/callback?", "/other?"),
    `${valid}&state=${request.state}`, `${valid}&code=other`, `${valid}#fragment`, `${valid}&redirect=other`, valid.replace(request.state, "other")]) {
    expect(() => validatedMcpRedirect(value, request)).toThrow();
  }
});
it("validates a single issuer in the callback without letting it expand the return destination", () => {
  const request = parameters;
  const valid = `${request.redirect_uri}?${new URLSearchParams({ code: "one-use", state: request.state, iss: new URL(request.resource).origin })}`;
  expect(validatedMcpRedirect(valid, request)).toBe(valid);
  for (const bad of [valid.replace("app.example.test", "evil.test"), `${valid}&iss=https%3A%2F%2Fapp.example.test`, `${valid}&next=https://evil.test`]) {
    expect(() => validatedMcpRedirect(bad, request)).toThrow();
  }
});
it("requires issuer identification for native app callbacks while accepting the matching origin", () => {
  const request = { ...parameters, client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: "http://127.0.0.1:49153/callback" };
  const withoutIssuer = `${request.redirect_uri}?${new URLSearchParams({ code: "one-use", state: request.state })}`;
  expect(() => validatedMcpRedirect(withoutIssuer, request)).toThrow();
  expect(validatedMcpRedirect(`${withoutIssuer}&${new URLSearchParams({ iss: new URL(request.resource).origin })}`, request)).toContain("iss=");
});

it("validates rejection callbacks with exact native state and issuer without accepting a success code", () => {
  const context = { client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: "http://127.0.0.1:50123/callback", resource: "https://app.example.test/mcp", state: parameters.state };
  const redirect_url = `${context.redirect_uri}?${new URLSearchParams({ error: "access_denied", state: context.state, iss: "https://app.example.test" })}`;
  expect(validatedMcpRequestCallback({ ...context, redirect_url }, true)).toBe(redirect_url);
  for (const bad of [`${redirect_url}&code=secret`, `${redirect_url}&error=access_denied`, redirect_url.replace("access_denied", "other"), redirect_url.replace("app.example.test", "evil.test")]) {
    expect(() => validatedMcpRequestCallback({ ...context, redirect_url: bad }, true)).toThrow();
  }
  expect(() => validatedMcpRequestCallback({ ...context, redirect_url }, false)).toThrow();
});
it("checks native callback context independently of a self-matching response URL", () => {
  const context = { client_id: "https://chatgpt.com/oauth/codex/client.json", redirect_uri: "http://127.0.0.2:50123/callback", resource: "https://app.example.test/mcp", state: parameters.state };
  const redirect_url = `${context.redirect_uri}?${new URLSearchParams({ code: "one-use", state: context.state, iss: "https://app.example.test" })}`;
  expect(() => validatedMcpRequestCallback({ ...context, redirect_url }, false)).toThrow();
});
