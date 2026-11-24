import type { CompanyDocumentUploadController } from "../../hooks/use-company-document-upload";
import type { CompanyDocumentUpload } from "../../types/company-people";

const SELECT_CLASS = "min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3";

export function DocumentUploadSelection({ controller }: { controller: CompanyDocumentUploadController }) {
  const { opened, draft, change, selectFile, preview, imageFailed } = controller;
  return <>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block space-y-1.5 text-sm font-medium text-slate-700">
        Update type
        <select value={draft.kind} className={SELECT_CLASS}
          onChange={(event) => change("kind", event.target.value as CompanyDocumentUpload["change_kind"])}>
          <option value="scan" disabled={!opened.current_document}>Better scan</option>
          <option value="renewal">{opened.current_document ? "Renewed passport" : "New passport"}</option>
          <option value="correction" disabled={!opened.current_document}>Correction</option>
        </select>
      </label>
      <label className="block space-y-1.5 text-sm font-medium text-slate-700">
        Document image
        <select value={draft.kind === "renewal" ? "front" : draft.side} disabled={draft.kind === "renewal"}
          className={SELECT_CLASS} onChange={(event) => change("side", event.target.value as CompanyDocumentUpload["side"])}>
          <option value="front">Passport front</option>
          <option value="back">Passport back</option>
          <option value="cover">Front cover</option>
          <option value="back_cover">Back cover</option>
          <option value="photo">Photo</option>
        </select>
      </label>
    </div>
    <label className="block space-y-2 text-sm font-medium text-slate-700">
      New image
      <input type="file" accept="image/jpeg,image/png,image/webp" required
        className="block w-full min-w-0 rounded-lg border border-slate-300 bg-white p-2 text-xs file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm"
        onChange={(event) => selectFile(event.target.files?.[0])} />
      <span className="block text-xs font-normal text-slate-500">JPEG, PNG or WebP · up to 20 MB</span>
    </label>
    {preview && (
      // This preview is the operator's locally selected, size-checked image.
      // eslint-disable-next-line @next/next/no-img-element
      <img src={preview} alt="New document image" className="max-h-72 w-full rounded-lg bg-white object-contain"
        onError={imageFailed} />
    )}
  </>;
}
