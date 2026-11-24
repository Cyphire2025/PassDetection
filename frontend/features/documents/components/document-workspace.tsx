"use client";

import type { DocumentDistributionLane } from "../config/document-distribution-lanes";
import { useDocumentWorkspace } from "../hooks/use-document-workspace";
import { DocumentWorkspaceHeader } from "./document-workspace-header";
import { DocumentWorkspaceUpload } from "./document-workspace-upload";
import { DocumentWorkspaceRoster } from "./document-workspace-roster";
import { DocumentWorkspaceActions } from "./document-workspace-actions";

export function DocumentWorkspace({ groupId, lane }: { groupId: string; lane: DocumentDistributionLane }) {
  const controller = useDocumentWorkspace(groupId, lane);
  return (
    <div className="flex flex-col gap-5">
      <DocumentWorkspaceHeader controller={controller} />
      <DocumentWorkspaceUpload controller={controller} />
      <DocumentWorkspaceRoster controller={controller} />
      <DocumentWorkspaceActions controller={controller} />
    </div>
  );
}
