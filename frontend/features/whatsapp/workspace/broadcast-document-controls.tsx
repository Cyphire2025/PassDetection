import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui";
import type { DistributionDocumentType } from "@/types/document-distribution.types";
import { distributionDocumentLabel } from "@/features/documents/config/document-distribution-lanes";
import type { BroadcastDocumentsController } from "./use-broadcast-documents";
import { documentTypes, filters } from "./broadcast-documents-model";
import { fieldClass, WorkspaceSearch } from "./workspace-ui";

export function BroadcastDocumentControls({ model }: { model: BroadcastDocumentsController }) {
  const { search, setSearch, setOffset, documentType, setDocumentType, refreshing, loading, passengerLinks, queries, filter, setFilter, counts, error } = model;
  return (<div className="space-y-4 p-5">
    <WorkspaceSearch
      value={search}
      onChange={(value) => {
        setSearch(value);
        setOffset(0);
      }}
      label="Search passenger documents"
      placeholder="Search passenger name or passport…"
    >
      <label className="text-xs text-slate-500">
        <span className="sr-only">Document type</span>
        <select
          aria-label="Document type"
          value={documentType}
          onChange={(event) => {
            setDocumentType(
              event.target.value as DistributionDocumentType,
            );
            setOffset(0);
          }}
          className={`${fieldClass} w-auto`}
        >
          {documentTypes.map((value) => (
            <option key={value} value={value}>
              {distributionDocumentLabel(value)}
            </option>
          ))}
        </select>
      </label>
      <Button
        variant="ghost"
        isLoading={refreshing && !loading}
        onClick={() => {
          void passengerLinks.refetch();
          for (const query of queries) void query.refetch();
        }}
        aria-label="Refresh documents"
      >
        <RefreshCw className="h-4 w-4" />
      </Button>
    </WorkspaceSearch>
    <div className="flex flex-wrap gap-2">
      {filters.map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={filter === value}
          aria-label={`${label} (${loading ? "loading" : error ? "unavailable" : counts[value]})`}
          onClick={() => {
            setFilter(value);
            setOffset(0);
          }}
          className={`rounded-lg px-3 py-2 text-xs font-medium ${filter === value ? "bg-blue-600 text-white" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
        >
          {label}
          <span className="ml-2 tabular-nums opacity-70">
            {loading || error
              ? "—"
              : counts[value]}
          </span>
        </button>
      ))}
    </div>
  </div>);
}
