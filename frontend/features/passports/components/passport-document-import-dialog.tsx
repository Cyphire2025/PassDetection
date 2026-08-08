"use client";

import { useMemo, useState } from "react";
import { Button, Card, CardContent } from "@/components/ui";
import type { PassportDocumentImportPreview } from "../api/passports.api";
import {
  formatBytes,
  matchPreviewFiles,
} from "../utils/passport-document-import";
import { DocumentCell } from "./passport-document-cell";

export function PassportDocumentImportProgress({
  processed,
  total,
  label,
}: {
  processed: number;
  total: number;
  label: string;
}) {
  const percentage = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const unit = total > 1024 * 1024 ? "bytes" : "files";
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/50 p-4">
      <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Passport document import</h2>
            <p className="mt-1 text-sm text-slate-500">{label}</p>
          </div>
          <div className="text-sm font-semibold text-blue-700">{percentage}%</div>
        </div>
        <div className="mt-5 h-3 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-blue-600 transition-all duration-150" style={{ width: `${Math.max(4, percentage)}%` }} />
        </div>
        <div className="mt-3 text-sm text-slate-500">
          {unit === "bytes"
            ? `${formatBytes(processed)} of ${formatBytes(total)}`
            : `${processed.toLocaleString()} of ${total.toLocaleString()} files checked`}
        </div>
      </div>
    </div>
  );
}

function PassportImportPreviewMatrix({
  preview,
  files,
}: {
  preview: PassportDocumentImportPreview;
  files: File[];
}) {
  const matchedFiles = useMemo(
    () => matchPreviewFiles(preview.accepted_documents, files),
    [files, preview.accepted_documents],
  );
  const passengers = useMemo(() => {
    const byPassenger = new Map<string, {
      id: string;
      name: string;
      staffCode: string;
      documents: Partial<Record<
        "photo" | "front" | "back",
        PassportDocumentImportPreview["accepted_documents"][number]
      >>;
    }>();
    preview.accepted_documents.forEach((document) => {
      if (!document.passenger_id || !document.document_type) return;
      const passenger = byPassenger.get(document.passenger_id) ?? {
        id: document.passenger_id,
        name: document.passenger_name || "Unnamed passenger",
        staffCode: document.staff_code || "",
        documents: {},
      };
      passenger.documents[document.document_type] = document;
      byPassenger.set(document.passenger_id, passenger);
    });
    return [...byPassenger.values()].sort((left, right) => (
      left.name.localeCompare(right.name, undefined, {
        sensitivity: "base",
        numeric: true,
      })
    ));
  }, [preview.accepted_documents]);

  return (
    <Card>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-sm">
            <caption className="sr-only">Imported passenger document preview</caption>
            <thead>
              <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                <th scope="col" className="px-5 py-4">Person</th>
                <th scope="col" className="px-5 py-4">Passport pic</th>
                <th scope="col" className="px-5 py-4">Passport front</th>
                <th scope="col" className="px-5 py-4">Passport back</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {passengers.map((passenger) => (
                <tr key={passenger.id} className="align-top">
                  <td className="px-5 py-4">
                    <div className="font-semibold text-slate-900">{passenger.name}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {passenger.staffCode || "No staff code"}
                    </div>
                  </td>
                  {(["photo", "front", "back"] as const).map((documentType) => {
                    const document = passenger.documents[documentType];
                    return (
                      <DocumentCell
                        key={documentType}
                        label={documentType}
                        file={document ? matchedFiles.get(document) : undefined}
                        filename={document?.filename}
                      />
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export function PassportDocumentImportDialog({
  preview,
  files,
  saving,
  onClose,
  onSave,
}: {
  preview: PassportDocumentImportPreview;
  files: File[];
  saving: boolean;
  onClose: () => void;
  onSave: () => void;
}) {
  const [step, setStep] = useState<"distribution" | "documents">("distribution");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
      <div className="flex max-h-[85vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="border-b border-slate-200 px-6 py-5">
          <h2 className="text-lg font-semibold text-slate-900">Passport document distribution</h2>
          <p className="mt-1 text-sm text-slate-500">
            {step === "distribution"
              ? `${preview.accepted_count} accepted, ${preview.rejected_count} rejected. Only accepted files will be saved.`
              : "Review every person against passport pic, passport front, and passport back before saving."}
          </p>
        </div>
        <div className="overflow-y-auto p-6">
          {step === "distribution" ? (
            <div className="grid gap-5 md:grid-cols-2">
              <section>
                <h3 className="mb-2 text-sm font-semibold text-emerald-800">Accepted ({preview.accepted_count})</h3>
                <div className="space-y-2">
                  {preview.accepted_documents.map((item) => (
                    <div key={`${item.filename}-${item.document_type}`} className="rounded-lg border border-emerald-100 bg-emerald-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-emerald-800">{item.passenger_name} - {item.document_type}</div>
                    </div>
                  ))}
                  {preview.accepted_count === 0 && <p className="text-sm text-slate-500">No files can be saved.</p>}
                </div>
              </section>
              <section>
                <h3 className="mb-2 text-sm font-semibold text-red-800">Rejected ({preview.rejected_count})</h3>
                <div className="space-y-2">
                  {preview.rejected_documents.map((item, index) => (
                    <div key={`${item.filename}-${index}`} className="rounded-lg border border-red-100 bg-red-50 p-3 text-sm">
                      <div className="font-medium text-slate-800">{item.filename}</div>
                      <div className="mt-1 text-red-700">{item.reason}</div>
                    </div>
                  ))}
                  {preview.rejected_count === 0 && <p className="text-sm text-slate-500">All files passed validation.</p>}
                </div>
              </section>
            </div>
          ) : (
            <PassportImportPreviewMatrix preview={preview} files={files} />
          )}
        </div>
        <div className="flex justify-end gap-3 border-t border-slate-200 px-6 py-4">
          <Button type="button" variant="outline" disabled={saving} onClick={onClose}>Cancel</Button>
          {step === "distribution" ? (
            <Button type="button" disabled={preview.accepted_count === 0} onClick={() => setStep("documents")}>
              Next
            </Button>
          ) : (
            <>
              <Button type="button" variant="secondary" disabled={saving} onClick={() => setStep("distribution")}>Back</Button>
              <Button type="button" disabled={saving || preview.accepted_count === 0} onClick={onSave}>
                {saving ? "Saving accepted files" : `Upload accepted (${preview.accepted_count})`}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
