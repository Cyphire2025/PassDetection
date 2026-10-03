"use client";

import { FileDown, FileUp, Plug, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils/format";
import { useMcpFileTransfer } from "../hooks/use-mcp-file-transfer";

const PURPOSES = { contact_broadcast: "Contact workbook for a broadcast", group_workbook: "Group workbook import", document_pdf: "Prepared document upload", export: "Prepared export" };

export function McpFileTransferPage({ id }: { id: string }) {
  return <main className="flex min-h-screen items-center justify-center px-4 py-12 sm:px-6"><div className="w-full max-w-xl">
    <div className="mb-6 flex items-center justify-center gap-2 text-sm font-semibold text-slate-700"><Plug className="h-5 w-5 text-blue-700" aria-hidden="true" />Global Connects</div>
    <Transfer key={id} id={id} />
  </div></main>;
}

function Transfer({ id }: { id: string }) {
  const { ticket, loading, busy, error, missing, file, download, saveInitiated, saved, confirming, expired, finished, blocked, credentialAvailable,
    refresh, upload, prepare, save, confirmSave, selectFile, retrySave } = useMcpFileTransfer(id);
  const title = missing ? "Open the transfer link from your app" : !ticket ? loading ? "Prepared file transfer" : "File transfer unavailable" : finished ? ticket.kind === "download" ? "File saved and confirmed" : "File uploaded"
    : expired ? "This transfer has expired" : ticket?.kind === "download" ? "Save your prepared file" : "Upload your prepared file";
  return <section aria-label="MCP file transfer" className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
    <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-700">{ticket?.kind === "download" ? <FileDown className="h-6 w-6" aria-hidden="true" /> : <FileUp className="h-6 w-6" aria-hidden="true" />}</div>
    <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
    <div aria-live="polite" className="mt-3 text-sm leading-6 text-slate-600">{missing ? <p>Open the file transfer link provided by ChatGPT or Codex. Reloading this page removes its access; reopen the original link if needed.</p>
      : loading ? <p>Checking the prepared transfer…</p> : finished ? <p>{ticket?.kind === "download" ? "The completed save was acknowledged. You can return to your app." : "The exact file was accepted for the prepared task. Return to your app to continue."}</p>
        : expired ? <p>Ask your app to prepare a new transfer link.</p> : <p>This transfer is limited to the file and destination prepared in your app.</p>}</div>
    {ticket ? <dl className="mt-6 space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
      <div><dt className="text-xs text-slate-500">Task</dt><dd className="mt-1 font-medium text-slate-900">{PURPOSES[ticket.purpose]}</dd></div>
      {ticket.destination_label ? <div><dt className="text-xs text-slate-500">Destination</dt><dd className="mt-1 break-words text-slate-800">{ticket.destination_label}</dd></div> : null}
      {ticket.document_type ? <div><dt className="text-xs text-slate-500">Document type</dt><dd className="mt-1 text-slate-800">{ticket.document_type}</dd></div> : null}
      <div><dt className="text-xs text-slate-500">File</dt><dd className="mt-1 break-words font-medium text-slate-900">{ticket.filename}</dd></div>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-500"><dd>{ticket.byte_size.toLocaleString()} bytes</dd><dd>Expires {formatDateTime(ticket.expires_at)}</dd></div>
    </dl> : null}
    {error ? <p role="alert" className="mt-5 rounded-lg bg-red-50 p-3 text-sm leading-6 text-red-800">{error}</p> : null}
    {ticket?.status === "failed" ? <p role="alert" className="mt-5 text-sm text-red-800">This transfer failed. Ask your app to prepare a new link.</p> : null}
    {ticket?.status === "transferring" ? <p role="status" className="mt-5 text-sm text-slate-600">This transfer is in progress. Check its status before trying again.</p> : null}
    {!missing && !finished && !expired ? <div className="mt-6 space-y-4">
      {ticket && ticket.kind !== "download" ? <><label className="block text-sm font-medium text-slate-800">Choose the prepared {ticket.kind === "upload_workbook" ? "XLSX" : "PDF"} file<input type="file" accept={ticket.kind === "upload_workbook" ? ".xlsx" : ".pdf"} disabled={blocked}
        onChange={(event) => { selectFile(event.target.files?.[0] ?? null); }} className="mt-2 block w-full rounded-lg border border-slate-300 p-3 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-blue-50 file:px-3 file:py-2 file:font-medium file:text-blue-800" /></label>
        <p className="text-xs leading-5 text-slate-500">We verify the file’s size and contents before uploading. Renaming the same file is allowed.</p>
        <Button disabled={blocked || !file} isLoading={busy} onClick={() => void upload()}>Verify and upload</Button></>
        : ticket ? <>{!download ? <Button disabled={blocked} isLoading={busy} onClick={() => void prepare()}>Prepare download</Button>
          : <><p role="status" className="text-sm text-green-800">File checked and ready to save.</p><Button disabled={blocked || saveInitiated} isLoading={busy} onClick={() => void save()}>Save file</Button></>}
          {confirming || saved ? <div className="rounded-lg border border-blue-100 bg-blue-50 p-4"><p className="text-sm leading-6 text-blue-950">{saved ? "Your file was saved. Confirm the completed transfer to finish." : "After your browser finishes saving the file, confirm below. If you cancelled the save, choose Save file again."}</p>
            <div className="mt-3 flex flex-wrap gap-2"><Button disabled={blocked || !download || !saveInitiated} isLoading={busy} onClick={() => void confirmSave()}>{saved ? "Confirm saved file" : "I saved this file"}</Button>
              {!saved ? <Button variant="secondary" disabled={busy} onClick={() => { retrySave(); }}>Try saving again</Button> : null}</div></div> : null}</> : null}
      {credentialAvailable && !busy ? <Button variant="secondary" size="sm" disabled={loading} onClick={() => void refresh()}><RefreshCw className="h-4 w-4" aria-hidden="true" />Check transfer status</Button> : null}
    </div> : null}
  </section>;
}
