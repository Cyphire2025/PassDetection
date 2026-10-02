"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Plug, RefreshCw, XCircle } from "lucide-react";
import { Button } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import { mcpRequestApi, McpRequestError } from "../api/mcp-request.api";
import { mcpClientNavigation, validatedMcpRequestCallback } from "../utils/consent";

const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function McpRequestWaitingPage({ requestId }: { requestId: string | string[] | undefined }) {
  const valid = typeof requestId === "string" && UUID.test(requestId);
  return <main className="flex min-h-screen items-center justify-center px-4 py-12 sm:px-6">
    <div className="w-full max-w-xl"><div className="mb-6 flex items-center justify-center gap-2 text-sm font-semibold text-slate-700"><Plug className="h-5 w-5 text-blue-700" aria-hidden="true" />Global Connects</div>
      {valid ? <WaitingRequest key={requestId} id={requestId} /> : <div className="rounded-2xl border border-slate-200 bg-white p-8"><h1 className="text-xl font-semibold text-slate-950">Start from your MCP app</h1><p className="mt-3 text-sm leading-6 text-slate-600">Open Global Connects in ChatGPT or Codex and click Authenticate to create an access request.</p></div>}
    </div>
  </main>;
}

function WaitingRequest({ id }: { id: string }) {
  const attempted = useRef(false);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["mcp-requester", id], queryFn: ({ signal }) => mcpRequestApi.status(id, signal),
    retry: false, refetchInterval: (current) => current.state.error instanceof McpRequestError
      && (current.state.error.status === 404 || current.state.error.status === 409) ? false : current.state.data?.status === "pending" ? 2500 : false,
    refetchOnWindowFocus: "always" });
  const request = query.data;
  const status = request?.status;
  useEffect(() => {
    if ((status !== "approved" && status !== "rejected") || query.isError || query.isFetching || attempted.current) return;
    attempted.current = true;
    setFinishing(true);
    void mcpRequestApi.finalize(id).then((response) => {
      const callback = validatedMcpRequestCallback(response, status === "rejected");
      mcpClientNavigation.assign(callback);
    }).catch(() => { setFinishError("Your request could not be returned to the app. Start Authenticate again from your app to try a new request."); setFinishing(false); });
  }, [id, status, query.isError, query.isFetching]);
  const ended = query.error instanceof McpRequestError && (query.error.status === 404 || query.error.status === 409);
  const declined = status === "rejected" || (status === "finalized" && !request?.approved_capabilities?.length);
  const successful = status === "approved" || (status === "finalized" && !declined);
  const title = ended ? "This request is no longer available" : status === "expired" ? "This request has expired"
    : declined ? "Access request declined" : status === "finalized" ? "Connection completed"
    : status === "approved" ? "Your access request was approved" : "Waiting for administrator approval";
  const Icon = successful ? CheckCircle2 : ended || status === "expired" || declined ? XCircle : Clock3;
  return <section aria-label="MCP access request" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
    <div className={`mb-5 flex h-12 w-12 items-center justify-center rounded-xl ${successful ? "bg-green-50 text-green-700" : "bg-blue-50 text-blue-700"}`}><Icon className="h-6 w-6" aria-hidden="true" /></div>
    <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
    <div aria-live="polite" className="mt-3 text-sm leading-6 text-slate-600">
      {ended ? <p>Start Authenticate again from your app to create a new access request.</p> : query.isPending ? <p>Checking your access request…</p> : query.isError ? <p>Your request status is temporarily unavailable.</p> : status === "pending" ? <p>Your access request is awaiting administrator approval. You can use Global Connects once an administrator approves this connection.</p>
        : status === "approved" ? <p>{finishing ? "Returning you to your app to finish connecting…" : "Your administrator approved this connection."}</p>
        : declined ? <p>Your administrator declined this connection. Contact them if you need access.</p>
        : status === "finalized" ? <p>This request has already returned to your app. You can close this tab.</p>
        : <p>Start Authenticate again from your app to create a new access request.</p>}
    </div>
    {request && !ended ? <div className="mt-6 space-y-4 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-medium text-slate-500">Connection</p><p className="mt-1 break-words text-sm font-semibold text-slate-900">{request.name}</p><p className="mt-1 text-xs text-slate-500">{request.client_name} · {request.device_platform}</p></div><div><p className="text-xs font-medium text-slate-500">Comparison code</p><p className="mt-1 font-mono text-xl font-semibold tracking-widest text-slate-950">{request.comparison_code}</p></div></div>
      {status === "pending" ? <><p className="border-t border-slate-200 pt-3 text-xs leading-5 text-slate-600">Share this code with your administrator so they can find the matching request.</p><p className="text-xs text-slate-500">Expires {formatDateTime(request.expires_at)}</p></> : null}
    </div> : null}
    {query.isError && !ended ? <div role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm text-red-800">The request could not be checked. Keep this tab open and try again.<Button variant="secondary" size="sm" className="mt-3" onClick={() => void query.refetch()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Check again</Button></div> : null}
    {finishError ? <p role="alert" className="mt-5 rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-900">{finishError}</p> : null}
    {status === "pending" && !ended ? <p className="mt-5 text-xs leading-5 text-slate-500">Keep this tab open. If your app’s sign-in window closes or times out, start Authenticate again from your app.</p> : null}
  </section>;
}
