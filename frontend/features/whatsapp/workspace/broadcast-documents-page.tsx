"use client";

import { ROUTES } from "@/constants/routes";
import { ArrowUpRight, Send } from "lucide-react";
import Link from "next/link";
import { Button, Skeleton } from "@/components/ui";
import { ErrorBanner, readErrorMessage } from "../components/whatsapp-dialog-ui";
import { BroadcastDocumentComposer } from "./document-composer";
import { useBroadcastDocuments } from "./use-broadcast-documents";
import { BroadcastDocumentControls } from "./broadcast-document-controls";
import { BroadcastDocumentTable } from "./broadcast-document-table";
import { EmptyWorkspace, WorkspacePagination } from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function BroadcastDocumentsPage() {
  const model = useBroadcastDocuments();
  const {
    group, documentType, composing, sources, setComposing, entries,
    loading, error, linked, displayed, pageOffset, setOffset,
  } = model;
  if (composing)
    return (
      <BroadcastDocumentComposer
        documentType={documentType}
        sources={sources}
        documentId={composing.documentId}
        onClose={() => setComposing(null)}
      />
    );
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            Passenger documents
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Assigned documents and delivery for this broadcast’s linked
            passengers.
          </p>
        </div>
        <Button
          disabled={
            group.is_archived ||
            loading || Boolean(error) ||
            !entries.some((entry) => entry.documents.length > 0)
          }
          onClick={() => setComposing({})}
        >
          <Send className="h-4 w-4" />
          Send documents
        </Button>
      </div>
      {!linked.length ? (
        <section className={styles.surface}>
          <EmptyWorkspace
            title="No linked documents yet"
            description="Documents appear here once this broadcast is linked to a trip group."
          />
        </section>
      ) : (
        <section className={styles.surface}>
          <BroadcastDocumentControls model={model} />
          {loading ? (
            <Skeleton className="m-5 h-64" />
          ) : error ? (
            <div className="p-5">
              <ErrorBanner
                message={readErrorMessage(
                  error,
                  "Passenger documents could not be loaded.",
                )}
              />
            </div>
          ) : !displayed.length ? (
            <EmptyWorkspace
              title="No matching passenger documents"
              description="Choose another document type, change the filter or clear your search."
            />
          ) : (
            <BroadcastDocumentTable model={model} />
          )}
          <WorkspacePagination
            total={displayed.length}
            offset={pageOffset}
            limit={50}
            onChange={setOffset}
            label="Passenger documents"
          />
          <div className="flex flex-wrap gap-3 border-t border-slate-100 px-5 py-3">
            {linked.map((source) => (
              <Link
                key={source.id}
                href={ROUTES.dashboard.documentGroup(source.id)}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-700"
              >
                Manage{" "}
                {linked.length > 1 ? source.name : "document assignments"}
                <ArrowUpRight className="h-3.5 w-3.5" />
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
