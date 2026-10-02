import { MCP_CAPABILITIES, type McpCapability, type McpConsentRequest, type McpOverview } from "../api/mcp.api";
import { effectiveMcpCapabilities } from "./read-only";

export type McpAuthorizationParameters = Record<string, string | string[] | undefined>;
export type McpAuthorizationRequest = Omit<McpConsentRequest, "name" | "device_platform">;

function safeCallback(value: string): URL | null {
  try {
    const url = new URL(value);
    return !url.username && !url.password && !url.hash && !url.search
      && (url.protocol === "https:" || (url.protocol === "http:" && url.hostname === "127.0.0.1")) ? url : null;
  } catch { return null; }
}

function approvedCallback(clientId: string, value: string, overview: McpOverview): boolean {
  if (Object.hasOwn(overview.approved_clients, clientId) && overview.approved_clients[clientId]?.includes(value)) return true;
  const direct = overview.direct_clients ?? {};
  if (!Object.hasOwn(direct, clientId)) return false;
  const requested = safeCallback(value);
  if (!requested) return false;
  return direct[clientId].some((published) => {
    if (published === value) return true;
    const callback = safeCallback(published);
    return callback?.protocol === "http:" && callback.hostname === "127.0.0.1" && !callback.port
      && requested.protocol === callback.protocol && requested.hostname === callback.hostname && requested.pathname === callback.pathname;
  });
}

/** Dashboard validation is for consent clarity; the server revalidates authority. */
export function parseMcpAuthorization(parameters: McpAuthorizationParameters, overview: McpOverview): McpAuthorizationRequest | null {
  const required = ["client_id", "redirect_uri", "resource", "state", "code_challenge", "code_challenge_method", "response_type", "scope"];
  if (Object.values(parameters).some(Array.isArray) || required.some((key) => typeof parameters[key] !== "string")) return null;
  const value = parameters as Record<string, string>;
  if (value.response_type !== "code" || value.code_challenge_method !== "S256"
    || !/^[A-Za-z0-9_-]{43}$/.test(value.code_challenge)
    || value.state.length < 16 || value.state.length > 512
    || value.resource !== overview.resource
    || !approvedCallback(value.client_id, value.redirect_uri, overview)) return null;
  const scopes = [...new Set(value.scope.trim().split(/\s+/))];
  if (!scopes.length || scopes.some((scope) => !Object.hasOwn(MCP_CAPABILITIES, scope) || !effectiveMcpCapabilities(overview).includes(scope as McpCapability))) return null;
  if (!safeCallback(value.redirect_uri)) return null;
  return { client_id: value.client_id, redirect_uri: value.redirect_uri, resource: value.resource, state: value.state,
    code_challenge: value.code_challenge, code_challenge_method: "S256", response_type: "code", scopes: scopes as McpCapability[] };
}

/** Never follow an arbitrary response destination, even after a successful POST. */
export function validatedMcpRedirect(value: string, request: Pick<McpAuthorizationRequest, "client_id" | "redirect_uri" | "resource" | "state">, rejected = false): string {
  const target = new URL(value);
  const approved = new URL(request.redirect_uri);
  const nativeClient = ["https://chatgpt.com/oauth/codex/client.json", "https://chatgpt.com/oauth/client.json"].includes(request.client_id);
  if (target.origin !== approved.origin || target.pathname !== approved.pathname || target.username || target.password || target.hash
    || target.searchParams.getAll("state").length !== 1 || target.searchParams.get("state") !== request.state
    || (!rejected && (target.searchParams.getAll("code").length !== 1 || !target.searchParams.get("code") || target.searchParams.has("error")))
    || (rejected && (target.searchParams.has("code") || target.searchParams.getAll("error").length !== 1 || target.searchParams.get("error") !== "access_denied"))
    || (nativeClient && !target.searchParams.has("iss"))
    || (target.searchParams.has("iss") && (target.searchParams.getAll("iss").length !== 1 || target.searchParams.get("iss") !== new URL(request.resource).origin))
    || [...target.searchParams.keys()].some((key) => key !== "state" && key !== (rejected ? "error" : "code") && key !== "iss")) {
    throw new Error("The client callback could not be verified. Restart sign-in from your client.");
  }
  return target.toString();
}

export function validatedMcpRequestCallback(value: { redirect_url: string; client_id: string; redirect_uri: string; resource: string; state: string }, rejected: boolean): string {
  if (!safeCallback(value.redirect_uri) || value.state.length < 16 || value.state.length > 512) throw new Error("The app return address could not be verified. Restart Authenticate from your app.");
  const callback = new URL(value.redirect_uri);
  if ((value.client_id === "https://chatgpt.com/oauth/codex/client.json" && (callback.protocol !== "http:" || callback.hostname !== "127.0.0.1" || callback.pathname !== "/callback"))
    || (value.client_id === "https://chatgpt.com/oauth/client.json" && value.redirect_uri !== "https://chatgpt.com/connector_platform_oauth_redirect")) throw new Error("The app return address could not be verified. Restart Authenticate from your app.");
  return validatedMcpRedirect(value.redirect_url, value, rejected);
}

export const mcpClientNavigation = { assign: (url: string) => window.location.assign(url) };
