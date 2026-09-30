"use client";

import { useState } from "react";
import { Badge } from "@/components/ui";
import type { McpOverview } from "../api/mcp.api";

const CONNECTOR_CLIENT = "global-connects-desktop";
const CONNECTOR_CALLBACK = "http://127.0.0.1:8765/callback";
const INSTALL_COMMANDS = [
  "uv venv --python 3.11 .venv",
  "uv pip install --python .venv/Scripts/python.exe --require-hashes -r requirements.lock",
  "uv pip install --python .venv/Scripts/python.exe --no-deps .",
  ".venv/Scripts/gc-mcp.exe --version",
].join("\n");

function PowerShellCommand({ children }: { children: string }) {
  return <pre className="mt-2 whitespace-pre-wrap break-all rounded-lg bg-slate-50 p-3 text-xs leading-5 text-slate-800"><code>{children}</code></pre>;
}

export function McpConnectorSetup({ overview }: { overview: McpOverview }) {
  const [reports, setReports] = useState(false);
  let origin: string | null = null;
  try { origin = new URL(overview.resource).origin; } catch { /* The endpoint is displayed by the parent for diagnosis. */ }
  const approved = overview.approved_clients[CONNECTOR_CLIENT]?.includes(CONNECTOR_CALLBACK) && origin;
  const quotedOrigin = origin ? `'${origin.replaceAll("'", "''")}'` : "'<application-origin>'";
  const command = `.venv/Scripts/gc-mcp.exe --origin ${quotedOrigin}`;
  const requestReports = reports && overview.capabilities.includes("mcp:read") && overview.capabilities.includes("mcp:export");
  return <section aria-label="Windows connector setup" className="space-y-4 rounded-xl border border-slate-200 p-5 lg:col-span-2">
    <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-base font-semibold text-slate-900">Windows connector 0.2.0</h2><Badge variant="warning">Client qualification in progress</Badge></div>
    <p className="text-sm leading-6 text-slate-600">Use the local connector to expose deployed application tools to Codex over stdio. This release supports Windows with CPython 3.11 and stores its authorization in Windows Credential Manager.</p>
    {!approved ? <p role="status" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">This deployment has not approved the desktop connector’s callback. An administrator must configure the approved client before sign-in can complete.</p> : null}
    <ol className="space-y-5 text-sm text-slate-700">
      <li><h3 className="font-medium text-slate-900">1. Install the reviewed source package</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">Obtain the version 0.2.0 connector source package from your application release administrator. A hosted installer is not published here. From its <code>mcp-connector</code> directory, use your approved <code>uv</code> installation to create a separate environment:</p>
        <details className="mt-2"><summary className="cursor-pointer text-sm font-medium text-blue-700">Show PowerShell installation commands</summary><PowerShellCommand>{INSTALL_COMMANDS}</PowerShellCommand></details>
        <p className="mt-2 text-xs text-slate-500">The version command must report 0.2.0. Keep this environment separate from the application server.</p>
      </li>
      <li><h3 className="font-medium text-slate-900">2. Sign in from the connector</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">Choose the access to request. This only changes the command below; permissions are granted after you run it, sign in and explicitly approve them in your browser.</p>
        <fieldset className="mt-3 space-y-2 text-sm"><legend className="mb-2 font-medium text-slate-700">What should Codex help with?</legend>
          <label className="flex items-start gap-2"><input type="radio" name="codex-setup-access" checked={!requestReports} onChange={() => setReports(false)} className="mt-1" /><span>Look up information</span></label>
          {overview.capabilities.includes("mcp:read") && overview.capabilities.includes("mcp:export") ? <label className="flex items-start gap-2"><input type="radio" name="codex-setup-access" checked={requestReports} onChange={() => setReports(true)} className="mt-1" /><span>Look up information and download reports</span></label> : null}
        </fieldset>
        <PowerShellCommand>{`${command} sign-in --scopes mcp:read${requestReports ? " mcp:export" : ""}`}</PowerShellCommand>
        <p className="mt-2 text-xs leading-5 text-slate-500">Review the connection name and selected permissions after superadmin sign-in and MFA. Report availability still depends on this website’s enabled features.</p>
      </li>
      <li><h3 className="font-medium text-slate-900">3. Add the local MCP server in Codex</h3>
        <dl className="mt-2 grid gap-3 rounded-lg bg-slate-50 p-3 text-xs sm:grid-cols-[auto_1fr]">
          <dt className="font-medium text-slate-500">Transport</dt><dd>stdio</dd>
          <dt className="font-medium text-slate-500">Command</dt><dd className="break-all">Absolute path to this installation’s <code>.venv/Scripts/gc-mcp.exe</code></dd>
          <dt className="font-medium text-slate-500">Arguments</dt><dd className="break-all"><code>--origin</code>, <code>{origin ?? "application public origin"}</code>, <code>serve</code></dd>
          <dt className="font-medium text-slate-500">Secret environment variables</dt><dd>None</dd>
        </dl>
        <p className="mt-2 text-xs leading-5 text-slate-500">Review these fields in your installed Codex client. The connector does not edit Codex configuration.</p>
        {requestReports ? <p className="mt-2 text-xs leading-5 text-slate-500">To save reports, also add <code>--download-directory</code> and the absolute path to an existing folder you choose to the server arguments. The connector creates new files there and does not overwrite existing files.</p> : null}
      </li>
    </ol>
    <details className="text-sm"><summary className="cursor-pointer font-medium text-slate-700">Revocation and sign-in recovery</summary>
      <p className="mt-2 text-xs leading-5 text-slate-500">Disconnect the named connection on this page to stop server access. If local authorization expires or refresh fails, run sign-in again. To clear only this connector’s saved Windows credential:</p>
      <PowerShellCommand>{`${command} forget`}</PowerShellCommand>
      <p className="mt-2 text-xs leading-5 text-slate-500">Clearing the local credential does not revoke the server connection. If a write or send is interrupted, check its existing record before repeating it.</p>
    </details>
    <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">Full workflow qualification remains in progress. Local file tools use exact files and a download folder selected in the connector startup arguments described in its README. PDF upload stages a file for a later workflow. Automatic handoff of new Codex attachments remains unqualified.</p>
  </section>;
}
