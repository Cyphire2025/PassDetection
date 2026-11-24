"use client";

import { useUploadLinkList } from "./use-upload-link-list";
import { UploadLinkListHeader } from "./upload-link-list-header";
import { UploadLinkListSummary } from "./upload-link-list-summary";
import { UploadLinkListSections } from "./upload-link-list-sections";
import { UploadLinkListActionDialogs, UploadLinkListCreateDialog } from "./upload-link-list-dialogs";

export function UploadLinkList() {
  const state = useUploadLinkList();
  const { copyError } = state;
  return (
    <div className="flex flex-col gap-5">
      <UploadLinkListHeader state={state} />
      <UploadLinkListCreateDialog state={state} />
      {copyError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {copyError}
        </div>
      )}
      <UploadLinkListSummary state={state} />
      <UploadLinkListSections state={state} />
      <UploadLinkListActionDialogs state={state} />
    </div>
  );
}
