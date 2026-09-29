import { MCP_CAPABILITIES, type McpCapability, type McpConsentRequest, type McpOverview } from "../api/mcp.api";

export type McpAuthorizationParameters = Record<string, string | string[] | undefined>;
export type McpAuthorizationRequest = Omit<McpConsentRequest, "name">;

/** Dashboard validation is for consent clarity; the server revalidates authority. */
export function parseMcpAuthorization(parameters: McpAuthorizationParameters, overview: McpOverview): McpAuthorizationRequest | null {
  const required = ["client_id", "redirect_uri", "resource", "state", "code_challenge", "code_challenge_method", "response_type", "scope"];
  if (Object.values(parameters).some(Array.isArray) || required.some((key) => typeof parameters[key] !== "string")) return null;
  const value = parameters as Record<string, string>;
  if (value.response_type !== "code" || value.code_challenge_method !== "S256"
    || !/^[A-Za-z0-9_-]{43}$/.test(value.code_challenge)
    || value.state.length < 16 || value.state.length > 512
    || value.resource !== overview.resource
    || !Object.hasOwn(overview.approved_clients, value.client_id)
    || !overview.approved_clients[value.client_id]?.includes(value.redirect_uri)) return null;
  const scopes = [...new Set(value.scope.trim().split(/\s+/))];
  if (!scopes.length || scopes.some((scope) => !Object.hasOwn(MCP_CAPABILITIES, scope) || !overview.capabilities.includes(scope as McpCapability))) return null;
  try {
    const redirect = new URL(value.redirect_uri);
    if (redirect.username || redirect.password || redirect.hash || redirect.search
      || (redirect.protocol !== "https:" && !(redirect.protocol === "http:" && redirect.hostname === "127.0.0.1"))) return null;
  } catch { return null; }
  return { client_id: value.client_id, redirect_uri: value.redirect_uri, resource: value.resource, state: value.state,
    code_challenge: value.code_challenge, code_challenge_method: "S256", response_type: "code", scopes: scopes as McpCapability[] };
}

/** Never follow an arbitrary response destination, even after a successful POST. */
export function validatedMcpRedirect(value: string, request: McpAuthorizationRequest): string {
  const target = new URL(value);
  const approved = new URL(request.redirect_uri);
  if (target.origin !== approved.origin || target.pathname !== approved.pathname || target.username || target.password || target.hash
    || target.searchParams.getAll("state").length !== 1 || target.searchParams.get("state") !== request.state
    || target.searchParams.getAll("code").length !== 1 || !target.searchParams.get("code")
    || [...target.searchParams.keys()].some((key) => key !== "state" && key !== "code")) {
    throw new Error("The client callback could not be verified. Restart sign-in from your client.");
  }
  return target.toString();
}

export const mcpClientNavigation = { assign: (url: string) => window.location.assign(url) };
