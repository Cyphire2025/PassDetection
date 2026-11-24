"use client";
import { useMemo, useState, type ReactNode } from "react";
import { Archive, ArrowLeft, Download, FileCheck2, FileQuestion, Plane } from "lucide-react";
import { Badge, Button, Card, CardContent, buttonVariants } from "@/components/ui";
import type { RenameDocumentBatch } from "@/types/document-rename.types";
import { cn } from "@/lib/utils/cn";

type RenameFilter = "visa" | "flight_ticket" | "unknown";
function detectedLabel(value: string) {
  if (value === "visa") return "Visa";
  if (value === "flight_ticket") return "Flight Ticket";
  return "Rejected";
}
function detectedBadge(value: string) {
  if (value === "visa") return "success";
  if (value === "flight_ticket") return "secondary";
  return "warning";
}
export function RenameResults({ batch, onBack }: { batch: RenameDocumentBatch; onBack: () => void }) {
  const [filter, setFilter] = useState<RenameFilter>("visa");
  const hasDownloadableDocuments =
    batch.status === "completed" && batch.visa_count + batch.ticket_count > 0;
  const filteredItems = useMemo(
    () =>
      batch.items
        .filter((item) => item.detected_type === filter)
        .slice()
        .sort((first, second) => first.renamed_filename.localeCompare(second.renamed_filename)),
    [batch.items, filter],
  );

  return (
    <div className="space-y-3">
      <div>
        <Button type="button" variant="secondary" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" />
          Back
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="flex flex-col gap-4 border-b border-slate-100 p-5 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-900">Rename Results</h2>
              <div className="mt-1 text-sm font-medium text-slate-700">{batch.title}</div>
              <p className="mt-1 text-sm text-slate-500">
                {batch.total_count} processed, {batch.visa_count} {batch.visa_count === 1 ? "visa" : "visas"}, {batch.ticket_count} flight {batch.ticket_count === 1 ? "ticket" : "tickets"}, {batch.unknown_count} rejected.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <FilterButton
                active={filter === "visa"}
                icon={<FileCheck2 className="h-3.5 w-3.5" />}
                activeClassName="border-green-200 bg-green-50 text-green-700"
                onClick={() => setFilter("visa")}
              >
                {batch.visa_count} {batch.visa_count === 1 ? "visa" : "visas"}
              </FilterButton>
              <FilterButton
                active={filter === "flight_ticket"}
                icon={<Plane className="h-3.5 w-3.5" />}
                activeClassName="border-blue-200 bg-blue-50 text-blue-700"
                onClick={() => setFilter("flight_ticket")}
              >
                {batch.ticket_count} {batch.ticket_count === 1 ? "ticket" : "tickets"}
              </FilterButton>
              <FilterButton
                active={filter === "unknown"}
                icon={<FileQuestion className="h-3.5 w-3.5" />}
                activeClassName="border-amber-200 bg-amber-50 text-amber-700"
                onClick={() => setFilter("unknown")}
              >
                {batch.unknown_count} rejected
              </FilterButton>
              {hasDownloadableDocuments ? (
                <a href={batch.zip_download_url} target="_blank" rel="noopener noreferrer" className={cn(buttonVariants())}>
                  <Archive className="h-4 w-4" />
                  Download ZIP
                </a>
              ) : batch.status === "processing" ? (
                <span className="self-center text-xs font-medium text-amber-700">
                  Upload incomplete — resume the same selection to finish
                </span>
              ) : (
                <span className="self-center text-xs font-medium text-amber-700">
                  No verified PDFs to download
                </span>
              )}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Renamed document results</caption>
              <thead>
                <tr className="border-b border-slate-100 text-xs uppercase tracking-wide text-slate-400">
                  <th scope="col" className="px-5 py-4">Original PDF</th>
                  <th scope="col" className="px-5 py-4">Renamed PDF</th>
                  <th scope="col" className="px-5 py-4">Detected</th>
                  <th scope="col" className="px-5 py-4">Extracted Name</th>
                  <th scope="col" className="px-5 py-4 text-right">Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filteredItems.map((item) => {
                  const downloadable =
                    item.status !== "rejected" &&
                    (item.detected_type === "visa" || item.detected_type === "flight_ticket") &&
                    Boolean(item.download_url);
                  return (
                    <tr key={item.id}>
                      <td className="px-5 py-4">
                        <div className="font-medium text-slate-900">{item.original_filename}</div>
                        {item.reason && <div className="mt-1 text-xs text-amber-700">{item.reason}</div>}
                      </td>
                      <td className="px-5 py-4">
                        {downloadable ? (
                          <a href={item.download_url} className="font-medium text-blue-700 hover:underline">
                            {item.renamed_filename}
                          </a>
                        ) : (
                          <span className="font-medium text-slate-500">Not renamed</span>
                        )}
                      </td>
                      <td className="px-5 py-4">
                        <Badge variant={detectedBadge(item.detected_type)}>
                          {detectedLabel(item.detected_type)}
                        </Badge>
                      </td>
                      <td className="px-5 py-4 text-slate-700">{item.extracted_name || "Not found"}</td>
                      <td className="px-5 py-4 text-right">
                        {downloadable ? (
                          <a href={item.download_url} className={cn(buttonVariants({ variant: "outline", size: "sm" }))}>
                            <Download className="h-4 w-4" />
                            File
                          </a>
                        ) : (
                          <span className="text-xs font-medium text-slate-400">Rejected</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {filteredItems.length === 0 && (
              <div className="border-t border-slate-100 p-8 text-center text-sm text-slate-500">
                No documents in this category.
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
function FilterButton({
  active,
  activeClassName,
  icon,
  children,
  onClick,
}: {
  active: boolean;
  activeClassName: string;
  icon: ReactNode;
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-10 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition ${
        active ? activeClassName : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}
