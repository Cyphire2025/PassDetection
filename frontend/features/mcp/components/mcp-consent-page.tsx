"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { Plug } from "lucide-react";
import { Badge, Button, Input } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import type { McpCapability, McpOverview } from "../api/mcp.api";
import { useMcpAuthorize, useMcpOverview } from "../hooks/use-mcp";
import { mcpClientNavigation, parseMcpAuthorization, validatedMcpRedirect, type McpAuthorizationParameters, type McpAuthorizationRequest } from "../utils/consent";
import { McpAccessBoundary, McpCapabilityPicker, McpError } from "./mcp-shared";

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
      <h1 className="text-lg font-semibold text-slate-950">Connection request could not be verified</h1><p className="mt-2 text-sm text-slate-700">Return to your approved MCP client and start sign-in again. No access has been granted.</p>
    </div> : null}
    {overview.data && request ? <ConsentForm key={JSON.stringify(request)} request={request} overview={overview.data} /> : null}
    <Link href={ROUTES.dashboard.mcp} className="inline-block text-sm font-medium text-blue-700 hover:underline">Return to MCP administration</Link>
  </div>;
}

function ConsentForm({ request, overview }: { request: McpAuthorizationRequest; overview: McpOverview }) {
  const [name, setName] = useState("");
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
    if (inFlight.current || !overview.enabled || !name.trim() || !selected.length) return;
    inFlight.current = true;
    setError(null);
    try {
      const result = await authorize.mutateAsync({ ...request, name: name.trim(), scopes: selected });
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
      <h1 className="text-xl font-semibold tracking-tight text-slate-950">Connect to Global Connects</h1><p className="mt-1 break-all text-sm text-slate-500">{request.client_id}</p>
    </div></div>
    <p className="mt-5 text-sm leading-6 text-slate-600">Review this client’s requested permissions. Your authorization expires within seven days, and you can revoke access at any time.</p>
    <dl className="mt-4 space-y-3 rounded-lg bg-slate-50 p-3 text-xs"><div><dt className="font-medium text-slate-500">Application endpoint</dt><dd className="mt-1 break-all text-slate-800">{request.resource}</dd></div>
      <div><dt className="font-medium text-slate-500">Return to client</dt><dd className="mt-1 break-all text-slate-800">{request.redirect_uri}</dd></div></dl>
    {!overview.enabled ? <p role="alert" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">MCP access is disabled. An administrator must enable access before you can connect.</p> : null}
    {overview.qualification !== "qualified" ? <Badge variant="warning" className="mt-4">Release qualification in progress</Badge> : null}
    <fieldset disabled={pending || !overview.enabled} className="mt-5 space-y-5">
      <Input label="Connection name" placeholder="For example, Nipun’s desktop" value={name} required maxLength={120} autoComplete="off" onChange={(event) => setName(event.target.value)} />
      <McpCapabilityPicker available={request.scopes} selected={selected} onChange={setSelected} />
      <p className="text-xs leading-5 text-slate-500">Deletion, removal and server control are unavailable through MCP. Recent multi-factor authentication is required to authorize this connection.</p>
    </fieldset>
    <div className="mt-4"><McpError error={error} /></div>
    <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
      {!pending ? <Link href={ROUTES.dashboard.mcp} className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900">Cancel</Link> : null}
      <Button type="submit" disabled={!overview.enabled || !name.trim() || !selected.length} isLoading={pending}>{redirecting ? "Returning to client…" : "Authorize connection"}</Button>
    </div>
  </form>;
}
