import { Archive, CalendarDays, CheckCircle2, Link2 } from "lucide-react";
import { WorkspaceSummaryItem, WorkspaceSummaryStrip } from "@/components/shared/workspace-ui";
import type { UploadLinkListState } from "./use-upload-link-list";

export function UploadLinkListSummary({ state }: { state: UploadLinkListState }) {
  const {
    isLoadingActive,
    isLoadingArchived,
    activeDataKnown,
    activeCount,
    closedCount,
    archivedDataKnown,
    archivedLinks,
    datedCount
  } = state;
  return (
    <WorkspaceSummaryStrip label="Group Link lifecycle summary">
      {isLoadingActive || isLoadingArchived ? (
        Array.from({ length: 4 }).map((_, index) => (
          <div key={index} className="h-[72px] animate-pulse bg-slate-100" />
        ))
      ) : (
        <>
          <WorkspaceSummaryItem
            label="Active links"
            value={activeDataKnown ? activeCount.toLocaleString() : "Unavailable"}
            helper="accepting uploads"
            icon={Link2}
            tone="success"

          />
          <WorkspaceSummaryItem
            label="Closed groups"
            value={activeDataKnown ? closedCount.toLocaleString() : "Unavailable"}
            helper="intake stopped"
            icon={CheckCircle2}

          />
          <WorkspaceSummaryItem
            label="Archived"
            value={archivedDataKnown ? archivedLinks.length.toLocaleString() : "Unavailable"}
            helper="retained history"
            icon={Archive}

          />
          <WorkspaceSummaryItem
            label="Travel date set"
            value={activeDataKnown && archivedDataKnown ? datedCount.toLocaleString() : "Unavailable"}
            helper="configured groups"
            icon={CalendarDays}
            tone="info"

          />
        </>
      )}
    </WorkspaceSummaryStrip>
  );
}
