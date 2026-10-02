"use client";

import type { McpOverview } from "../api/mcp.api";
import { CHATGPT_CLIENT_ID, DIRECT_CODEX_CLIENT_ID } from "./mcp-access-model";

export function McpDirectSetup({ overview, label = "Direct MCP setup" }: { overview: McpOverview; label?: string }) {
  const available = !!(overview.direct_clients?.[DIRECT_CODEX_CLIENT_ID]?.length || overview.direct_clients?.[CHATGPT_CLIENT_ID]?.length);
  return <section aria-label={label} className="space-y-4 rounded-xl border border-slate-200 p-5 lg:col-span-2">
    <h2 className="text-base font-semibold text-slate-900">Add Global Connects on Windows or macOS</h2>
    <p className="text-sm leading-6 text-slate-600">Open the custom MCP form in ChatGPT or Codex and use these settings. Your app connects directly to the remote server.</p>
    {!available ? <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Direct app sign-in has not been enabled on this deployment yet. Complete the server setup before connecting.</p> : null}
    <dl className="grid gap-3 rounded-lg bg-slate-50 p-4 text-sm sm:grid-cols-[auto_1fr]">
      <dt className="font-medium text-slate-500">Name</dt><dd>Global Connects</dd>
      <dt className="font-medium text-slate-500">Type</dt><dd>Streamable HTTP</dd>
      <dt className="font-medium text-slate-500">URL</dt><dd className="break-all">{overview.resource}</dd>
      <dt className="font-medium text-slate-500">Bearer token env var</dt><dd>Leave empty</dd>
      <dt className="font-medium text-slate-500">Headers</dt><dd>Leave empty</dd>
      <dt className="font-medium text-slate-500">Headers from environment variables</dt><dd>Leave empty</dd>
    </dl>
    <ol className="space-y-3 text-sm leading-6 text-slate-600">
      <li><strong className="text-slate-900">1. Save the MCP.</strong> Use your app’s native sign-in or connect action to open Global Connects in your browser.</li>
      <li><strong className="text-slate-900">2. Request access.</strong> Click Authenticate in your app. A browser tab opens automatically with your pending request and a comparison code. Keep it open while your administrator approves the matching request.</li>
      <li><strong className="text-slate-900">3. Finish connecting.</strong> Approval returns you to your app automatically. The approved connection appears in Devices with its own Enable and Disable button.</li>
    </ol>
    <p className="text-xs leading-5 text-slate-500">Support for file attachments and downloads depends on the client and enabled tools.</p>
  </section>;
}
