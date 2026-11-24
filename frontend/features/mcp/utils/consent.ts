import type { McpRequestCallback } from "../api/mcp.api";

function safeCallback(value: string): URL | null {
  try {
    const url = new URL(value);
    return !url.username && !url.password && !url.hash && !url.search
      && (url.protocol === "https:" || (url.protocol === "http:" && url.hostname === "127.0.0.1")) ? url : null;
  } catch { return null; }
}

/** Never follow an arbitrary response destination, even after a successful POST. */
export function validatedMcpRedirect(value: string, request: Pick<McpRequestCallback, "client_id" | "redirect_uri" | "resource" | "state">, rejected = false): string {
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
