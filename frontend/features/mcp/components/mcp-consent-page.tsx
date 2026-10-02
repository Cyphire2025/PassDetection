"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Plug } from "lucide-react";
import { Button, Input } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import type { McpCapability, McpDevicePlatform, McpOverview } from "../api/mcp.api";
import { useMcpAuthorize, useMcpOverview } from "../hooks/use-mcp";
import { mcpClientNavigation, parseMcpAuthorization, validatedMcpRedirect, type McpAuthorizationParameters, type McpAuthorizationRequest } from "../utils/consent";
import { effectiveMcpCapabilities, isMcpReadOnlyMode } from "../utils/read-only";
import { McpAccessBoundary, McpCapabilityPicker, McpError } from "./mcp-shared";
import { CODEX_CLIENT_ID, DIRECT_CODEX_CLIENT_ID, CHATGPT_CLIENT_ID } from "./mcp-access-model";

export function McpConsentPage({ parameters }: { parameters: McpAuthorizationParameters }) {
  return <McpAccessBoundary><ConsentRequest parameters={parameters} /></McpAccessBoundary>;
}

function ConsentRequest({ parameters }: { parameters: McpAuthorizationParameters }) {
  const overview = useMcpOverview();
  const request = overview.data ? parseMcpAuthorization(parameters, overview.data) : null;
  return <div className="mx-auto max-w-2xl space-y-4 py-4">
    <McpError error={overview.error} onRetry={() => void overview.refetch()} />
    {overview.isPending ? <p role="status" className="text-sm text-slate-500">Checking the connection request…</p> : null}
    {overview.data && !request ? <div role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-6">
      <h1 className="text-lg font-semibold text-slate-950">Connection request could not be verified</h1><p className="mt-2 text-sm text-slate-700">Return to the app you are connecting and start sign-in again. No access has been granted.</p>
    </div> : null}
    {overview.data && request ? <ConsentForm key={JSON.stringify(request)} request={request} overview={overview.data} unavailable={overview.isError || overview.isFetching} /> : null}
    <Link href={ROUTES.dashboard.mcp} className="inline-block text-sm font-medium text-blue-700 hover:underline">Return to Codex access</Link>
  </div>;
}

function ConsentForm({ request, overview, unavailable }: { request: McpAuthorizationRequest; overview: McpOverview; unavailable: boolean }) {
  const isCodex = [CODEX_CLIENT_ID, DIRECT_CODEX_CLIENT_ID].includes(request.client_id);
  const appName = isCodex ? "Codex" : request.client_id === CHATGPT_CLIENT_ID ? "ChatGPT" : overview.client_names?.[request.client_id] ?? "app";
  const [name, setName] = useState("");
  const [platform, setPlatform] = useState<McpDevicePlatform | "">("");
  const [selected, setSelected] = useState<McpCapability[]>(request.scopes);
  const [error, setError] = useState<unknown>(null);
  const [redirecting, setRedirecting] = useState(false);
  const inFlight = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const authorize = useMcpAuthorize();
  const pending = authorize.isPending || redirecting;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current || !overview.enabled || unavailable || !name.trim() || !platform || !selected.length || selected.some((scope) => !effectiveMcpCapabilities(overview).includes(scope))) return;
    inFlight.current = true;
    setError(null);
    try {
      const result = await authorize.mutateAsync({ ...request, name: name.trim(), device_platform: platform, scopes: selected });
      if (!mounted.current) return;
      const redirect = validatedMcpRedirect(result.redirect_url, request);
      setRedirecting(true);
      mcpClientNavigation.assign(redirect);
    } catch (cause) {
      if (!mounted.current) return;
      setError(cause);
      inFlight.current = false;
    }
  };
  return <form onSubmit={submit} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-7">
    <div className="flex items-start gap-3"><span className="rounded-xl border border-slate-200 p-3 text-slate-600"><Plug className="h-5 w-5" aria-hidden="true" /></span><div>
      <h1 className="text-xl font-semibold tracking-tight text-slate-950">{appName === "app" ? "Connect an approved app" : `Connect ${appName}`}</h1><p className="mt-1 text-sm text-slate-500">Choose how it can help you in Global Connects.</p>
    </div></div>
    <p className="mt-5 text-sm leading-6 text-slate-600">Name this connection so you can recognize it in Devices, then review its permissions. Access lasts up to seven days. Enable or disable it from the Codex access page at any time.</p>
    {isMcpReadOnlyMode(overview) ? <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-950">This is a read-only connection. Only the sidebar sections allowed on the Codex access page can be read. Saved section settings apply to every connection.</p> : null}
    {!overview.enabled ? <p role="alert" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{overview.deployment_enabled
      ? "Access is paused. Resume it on the Codex access page before connecting."
      : "Connections are not available on this site yet."}</p> : null}
    <fieldset disabled={pending || !overview.enabled || unavailable} className="mt-5 space-y-5">
      <Input label="Connection name" placeholder="For example, Office Windows or My MacBook" value={name} required maxLength={120} autoComplete="off" onChange={(event) => setName(event.target.value)} />
      <label className="block text-sm font-medium text-slate-700">Device platform
        <select value={platform} onChange={(event) => setPlatform(event.target.value as McpDevicePlatform | "")} className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm" required>
          <option value="" disabled>Choose a platform</option>
          <option value="Windows">Windows</option><option value="macOS">macOS</option><option value="Other">Other / cloud account</option>
        </select>
      </label>
      <p className="text-xs leading-5 text-slate-500">The name and platform are labels you choose. A ChatGPT connection may be shared across devices signed in to the same account; this does not identify a physical computer.</p>
      <McpCapabilityPicker available={request.scopes} selected={selected} onChange={setSelected} />
      <p className="text-xs leading-5 text-slate-500">This connection cannot delete records or files, or control the server. For security, you may need to confirm your identity before connecting.</p>
    </fieldset>
    <div className="mt-4"><McpError error={error} /></div>
    <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
      {!pending ? <Link href={ROUTES.dashboard.mcp} className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900">Cancel</Link> : null}
      <Button type="submit" disabled={unavailable || !overview.enabled || !name.trim() || !platform || !selected.length} isLoading={pending}>{redirecting ? "Finishing connection…" : `Connect ${appName}`}</Button>
    </div>
    <details className="mt-6 border-t border-slate-200 pt-4 text-sm">
      <summary className="cursor-pointer font-medium text-slate-600">Advanced connection details</summary>
      <dl className="mt-3 space-y-3 rounded-lg bg-slate-50 p-3 text-xs">
        <div><dt className="font-medium text-slate-500">Client identifier</dt><dd className="mt-1 break-all text-slate-800">{request.client_id}</dd></div>
        <div><dt className="font-medium text-slate-500">Application endpoint</dt><dd className="mt-1 break-all text-slate-800">{request.resource}</dd></div>
        <div><dt className="font-medium text-slate-500">Return address</dt><dd className="mt-1 break-all text-slate-800">{request.redirect_uri}</dd></div>
        <div><dt className="font-medium text-slate-500">Requested permission codes</dt><dd className="mt-1 break-all text-slate-800">{request.scopes.join(", ")}</dd></div>
        <div><dt className="font-medium text-slate-500">Release qualification</dt><dd className="mt-1 text-slate-800">{overview.qualification}</dd></div>
      </dl>
    </details>
  </form>;
}
