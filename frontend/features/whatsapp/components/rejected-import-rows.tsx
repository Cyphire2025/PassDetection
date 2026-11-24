"use client";

import { useState } from "react";
import { WorkspacePagination } from "@/components/shared/workspace-pagination";
import { clampPageOffset } from "@/lib/utils/pagination";
import type { RejectedContactDraft } from "../utils/recipient-import-state";

/** Keep all imported rows in the draft while bounding the mounted review cards. */
export function RejectedImportRows({ rows }: { rows: RejectedContactDraft[] }) {
  const [offset, setOffset] = useState(0);
  const pageOffset = clampPageOffset(offset, rows.length, 50);
  if (!rows.length) return null;

  return (
    <>
      <div className="mt-3 space-y-2" aria-label="Rejected spreadsheet rows">
        {rows.slice(pageOffset, pageOffset + 50).map((row, index) => (
          <article
            key={`${row.source_file_name}:${row.sheet_name}:${row.row_number}:${pageOffset + index}`}
            className="rounded-lg border border-amber-200 bg-white p-3 text-xs text-slate-700"
          >
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="min-w-0">
                <span className="font-semibold text-amber-900">Source</span>
                <p className="break-words">{row.source_file_name}</p>
              </div>
              <div>
                <span className="font-semibold text-amber-900">Sheet and row</span>
                <p>{row.sheet_name}, row {row.row_number}</p>
              </div>
              <div className="min-w-0">
                <span className="font-semibold text-amber-900">Entered name</span>
                <p className="break-words">{row.raw_name?.trim() || "Blank"}</p>
              </div>
              <div className="min-w-0">
                <span className="font-semibold text-amber-900">Entered phone</span>
                <p className="break-all font-mono">{row.raw_phone_number?.trim() || "Blank"}</p>
              </div>
            </div>
            <p className="mt-3 break-words text-amber-900">{row.reason}</p>
          </article>
        ))}
      </div>
      {rows.length > 50 && <WorkspacePagination total={rows.length} offset={pageOffset}
        limit={50} onChange={setOffset} label="Rejected spreadsheet rows" />}
    </>
  );
}
