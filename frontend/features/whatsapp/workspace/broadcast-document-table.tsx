import { FileText } from "lucide-react";
import { Button } from "@/components/ui";
import type { BroadcastDocumentsController } from "./use-broadcast-documents";
import { DeliveryBadge, tableClass } from "./workspace-ui";

export function BroadcastDocumentTable({ model }: { model: BroadcastDocumentsController }) {
  const { displayed, pageOffset, linked, group, setComposing } = model;
  return (<div className="overflow-x-auto">
    <table className={tableClass}>
      <thead>
        <tr>
          <th>Passenger</th>
          <th>Passport</th>
          <th>Documents</th>
          <th>Delivery</th>
          <th>
            <span className="sr-only">Actions</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {displayed
          .slice(pageOffset, pageOffset + 50)
          .map(({ row, source, documents }) => (
            <tr key={`${source.id}:${row.passenger_id}`}>
              <td>
                <p className="font-medium text-slate-900">
                  {row.passenger_name}
                </p>
                {linked.length > 1 && (
                  <p className="mt-1 text-xs text-slate-400">
                    {source.name}
                  </p>
                )}
              </td>
              <td className="text-slate-500">
                {row.passport_number || "—"}
              </td>
              <td className="min-w-56 max-w-sm">
                {documents.length ? (
                  <div className="space-y-3">
                    {documents.map((document) => (
                      <div key={document.id}>
                        {document.url ? (
                          <a
                            href={document.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-start gap-2 text-xs font-medium text-blue-700 hover:underline"
                          >
                            <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                            <span className="break-words">
                              {document.original_filename}
                            </span>
                          </a>
                        ) : (
                          <span className="text-xs text-slate-600">
                            {document.original_filename}
                          </span>
                        )}
                        <p className="mt-1 text-[11px] text-slate-400">
                          {document.source === "manual"
                            ? "Uploaded"
                            : "From email"}{" "}
                          ·{" "}
                          {Math.round(
                            document.match_confidence *
                            (document.match_confidence <= 1
                              ? 100
                              : 1),
                          )}
                          % match
                        </p>
                      </div>
                    ))}
                  </div>
                ) : (
                  <span className="text-xs text-amber-700">
                    Document missing
                  </span>
                )}
              </td>
              <td>
                {documents.length ? (
                  <div className="space-y-2">
                    {documents.map((document) => (
                      <div key={document.id}>
                        <DeliveryBadge
                          status={document.delivery_status}
                        />
                        {document.sent_to && (
                          <p className="mt-1 text-[11px] text-slate-400">
                            {document.sent_to}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <span className="text-slate-300">—</span>
                )}
              </td>
              <td>
                {documents
                  .filter((document) => document.can_resend)
                  .map((document) => (
                    <Button
                      key={document.id}
                      size="sm"
                      variant="ghost"
                      disabled={group.is_archived}
                      onClick={() =>
                        setComposing({ documentId: document.id })
                      }
                    >
                      Resend{documents.length > 1 ? " PDF" : ""}
                    </Button>
                  ))}
              </td>
            </tr>
          ))}
      </tbody>
    </table>
  </div>);
}
