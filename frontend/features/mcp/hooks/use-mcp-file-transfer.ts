import { useEffect, useRef, useState } from "react";
import { mcpTransferApi, McpTransferError, type McpFileTransfer } from "../api/mcp-transfer.api";
import { captureTransferToken, MCP_TRANSFER_ID, samePreparedTransfer, validTransfer, verifiedDownload, verifySelectedFile } from "../utils/file-transfer";
import { saveTransferFile } from "../utils/save-transfer-file";

export function useMcpFileTransfer(id: string) {
  const token = useRef<string | null | undefined>(undefined);
  const inFlight = useRef(false);
  const lifetime = useRef<AbortController | null>(null);
  const [ticket, setTicket] = useState<McpFileTransfer | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [credentialAvailable, setCredentialAvailable] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [download, setDownload] = useState<Blob | null>(null);
  const [saveInitiated, setSaveInitiated] = useState(false);
  const [saved, setSaved] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const confirmed = (current: McpFileTransfer, previous?: McpFileTransfer) => {
    if (!validTransfer(current, id) || (previous && !samePreparedTransfer(previous, current)))
      throw new Error("This transfer could not be verified. Ask your app for a new link.");
    setTicket(current);
    if (current.status === "failed" || current.delivered || (current.kind !== "download" && current.status === "completed")) { token.current = null; setCredentialAvailable(false); }
  };
  const failed = (cause: unknown) => {
    if (cause instanceof McpTransferError && [401, 403, 404, 422].includes(cause.status)) { token.current = null; setCredentialAvailable(false); }
    setError(cause instanceof Error ? cause.message : "The file transfer could not be completed. Try again.");
  };
  const refresh = async () => {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted || !token.current || inFlight.current) return;
    setLoading(true); setError(null);
    try { const current = await mcpTransferApi.status(id, token.current, signal); signal.throwIfAborted(); confirmed(current, ticket ?? undefined); }
    catch (cause) { if (!signal.aborted) failed(cause); }
    finally { if (!signal.aborted) setLoading(false); }
  };
  useEffect(() => {
    if (token.current === undefined) token.current = captureTransferToken();
    if (!MCP_TRANSFER_ID.test(id) || !token.current) { setMissing(true); setLoading(false); return; }
    setCredentialAvailable(true);
    const controller = new AbortController();
    lifetime.current = controller;
    void mcpTransferApi.status(id, token.current, controller.signal).then((current) => {
      if (!controller.signal.aborted) confirmed(current);
    }).catch((cause) => { if (!controller.signal.aborted) failed(cause); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  // The credential belongs only to this route instance; it is never cached or persisted.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  const expired = ticket ? Date.parse(ticket.expires_at) <= now : false;
  const finished = ticket?.kind === "download" ? ticket.delivered : ticket?.status === "completed";
  const blocked = loading || busy || expired || !ticket || !credentialAvailable || ticket.status === "failed" || ticket.status === "transferring" || !!finished;
  const run = async (action: (current: McpFileTransfer, credential: string, signal: AbortSignal) => Promise<void>) => {
    const signal = lifetime.current?.signal;
    if (!signal || signal.aborted || blocked || inFlight.current || !ticket || !token.current) return;
    inFlight.current = true; setBusy(true); setError(null);
    try { await action(ticket, token.current, signal); }
    catch (cause) { if (!signal.aborted) failed(cause); }
    finally { inFlight.current = false; if (!signal.aborted) setBusy(false); }
  };
  const upload = () => run(async (current, credential, signal) => {
    if (!file) return;
    await verifySelectedFile(file, current, signal);
    const response = await mcpTransferApi.upload(current, credential, file, signal);
    signal.throwIfAborted();
    if (response.status !== "completed") throw new Error("The upload has not been confirmed. Check its status before trying again.");
    confirmed(response, current); setFile(null);
  });
  const prepare = () => run(async (current, credential, signal) => {
    const response = await mcpTransferApi.download(id, credential, signal);
    const blob = await verifiedDownload(response, current, signal);
    signal.throwIfAborted(); setDownload(blob);
  });
  const acknowledge = async (current: McpFileTransfer, credential: string, signal: AbortSignal) => {
    const response = await mcpTransferApi.acknowledge(current, credential, signal);
    signal.throwIfAborted();
    if (!response.delivered || !response.download_completed) throw new Error("Your save has not been confirmed. Try confirming again.");
    confirmed(response, current); setDownload(null); setConfirming(false);
  };
  const save = () => run(async (current, credential, signal) => {
    if (!download) return;
    const result = await saveTransferFile(download, current.filename, current.media_type, signal);
    signal.throwIfAborted();
    setSaveInitiated(true);
    if (result === "saved") { setSaved(true); await acknowledge(current, credential, signal); }
    else setConfirming(true);
  });
  return { ticket, loading, busy, error, missing, file, download, saveInitiated, saved, confirming, expired, finished, blocked, credentialAvailable,
    refresh, upload, prepare, save, confirmSave: () => run(acknowledge),
    selectFile: (selected: File | null) => { setFile(selected); setError(null); },
    retrySave: () => { setSaveInitiated(false); setConfirming(false); } };
}
