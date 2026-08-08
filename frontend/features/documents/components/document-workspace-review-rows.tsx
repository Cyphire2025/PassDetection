import { Badge } from "@/components/ui";
import { formatConfidence } from "@/lib/utils/format";
import type {
  DistributedDocument,
  DistributionDocumentType,
  DocumentPassengerReviewRow,
} from "@/types/document-distribution.types";
import {
  DocumentRowActionMenu,
  DocumentSentStatus,
  MatchBadge,
} from "./document-workspace-review";

interface DocumentWorkspaceReviewRowsProps {
  rows: DocumentPassengerReviewRow[];
  documentsByPassengerId: ReadonlyMap<string, DistributedDocument[]>;
  activeSelectedAssignedDocumentIdSet: ReadonlySet<string>;
  documentType: DistributionDocumentType;
  showRowActions: boolean;
  removalPending: boolean;
  reuploadPending: boolean;
  searchQuery: string;
  onToggleRowDocuments: (documentIds: string[], selected: boolean) => void;
  onReupload: (passengerId: string, file: File) => void;
  onRemoveAssignment: (documentId: string) => void;
  onResend: (documentId: string) => void;
}

export function DocumentWorkspaceReviewRows({
  rows,
  documentsByPassengerId,
  activeSelectedAssignedDocumentIdSet,
  documentType,
  showRowActions,
  removalPending,
  reuploadPending,
  searchQuery,
  onToggleRowDocuments,
  onReupload,
  onRemoveAssignment,
  onResend,
}: DocumentWorkspaceReviewRowsProps) {
  return (
    <tbody className="divide-y divide-slate-100">
      {rows.map((row) => {
        const documents = documentsByPassengerId.get(row.passenger_id) ?? [];
        const rowDocumentIds = documents.map((document) => document.id);
        const rowAssignmentsSelected =
          rowDocumentIds.length > 0
          && rowDocumentIds.every((id) =>
            activeSelectedAssignedDocumentIdSet.has(id),
          );
        return (
          <tr key={row.passenger_id}>
            <td className="px-3 py-4 align-top">
              {documents.length > 0 ? (
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300"
                  aria-label={`Select all assignments for ${row.passenger_name}`}
                  checked={rowAssignmentsSelected}
                  disabled={removalPending}
                  onChange={(event) =>
                    onToggleRowDocuments(rowDocumentIds, event.target.checked)
                  }
                />
              ) : (
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300"
                  aria-label={`No document available for ${row.passenger_name}`}
                  disabled
                />
              )}
            </td>
            <td className="min-w-0 px-3 py-4 align-top">
              <div className="break-words font-semibold text-slate-900">{row.passenger_name}</div>
              <div className="mt-1 text-xs text-slate-500">
                {row.departure_city || "No departure city"}
              </div>
              {documents.length > 1 && (
                <Badge variant="outline" className="mt-2 whitespace-nowrap">
                  {documents.length} saved documents
                </Badge>
              )}
            </td>
            <td className="break-words px-3 py-4 align-top text-slate-700">
              {row.passport_number || "Not set"}
            </td>
            <td className="min-w-0 px-3 py-4 align-top">
              {documents.length > 0 ? (
                <div className="divide-y divide-slate-100">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex min-h-16 flex-col justify-center py-2 first:pt-0 last:pb-0"
                    >
                      <a
                        href={document.url ?? "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="break-words font-medium text-blue-700 hover:underline"
                      >
                        {document.original_filename}
                      </a>
                      <div className="mt-1 text-xs text-slate-500">
                        {document.source === "email" ? "Saved from email" : "Manual upload"}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-slate-400">Empty</span>
              )}
            </td>
            <td className="px-3 py-4 align-top text-slate-700">
              {documents.length > 0 ? (
                <div className="divide-y divide-slate-100">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0"
                    >
                      {formatConfidence(document.match_confidence)}
                    </div>
                  ))}
                </div>
              ) : (
                "-"
              )}
            </td>
            <td className="px-3 py-4 align-top">
              {documents.length > 0 ? (
                <div className="divide-y divide-slate-100">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0"
                    >
                      <MatchBadge status={document.match_status} />
                    </div>
                  ))}
                </div>
              ) : (
                <MatchBadge status="no_document" />
              )}
            </td>
            <td className="min-w-0 px-3 py-4 align-top">
              {documents.length > 0 ? (
                <div className="divide-y divide-slate-100">
                  {documents.map((document) => (
                    <div
                      key={document.id}
                      className="flex min-h-16 items-center py-2 first:pt-0 last:pb-0"
                    >
                      <DocumentSentStatus
                        status={document.delivery_status}
                        sentTo={document.sent_to}
                        sentAt={document.last_sent_at}
                        canResend={document.can_resend}
                        onResend={() => onResend(document.id)}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <span className="text-slate-400">&mdash;</span>
              )}
            </td>
            {showRowActions && (
              <td className="px-3 py-4 text-right align-top">
                <DocumentRowActionMenu
                  row={row}
                  documents={documents}
                  documentType={documentType}
                  pending={reuploadPending || removalPending}
                  onReupload={(file) => onReupload(row.passenger_id, file)}
                  onRemoveAssignment={onRemoveAssignment}
                />
              </td>
            )}
          </tr>
        );
      })}
      {rows.length === 0 && (
        <tr>
          <td
            colSpan={showRowActions ? 8 : 7}
            className="px-5 py-10 text-center text-sm text-slate-500"
          >
            {searchQuery.trim()
              ? "No passenger names match this search and filter."
              : "No passengers match this filter."}
          </td>
        </tr>
      )}
    </tbody>
  );
}
