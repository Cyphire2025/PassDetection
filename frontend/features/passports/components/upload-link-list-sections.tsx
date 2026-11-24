import { ChevronDown, Link2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceEmptyState, WorkspaceErrorNotice, WorkspaceToolbar } from "@/components/shared/workspace-ui";
import { UploadLinkTable } from "./upload-link-table";
import type { UploadLinkListState } from "./use-upload-link-list";
function LoadingRows() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-12 rounded-lg bg-slate-100" />
      <div className="h-12 rounded-lg bg-slate-100" />
      <div className="h-12 rounded-lg bg-slate-100" />
    </div>
  );
}

export function UploadLinkListSections({ state }: { state: UploadLinkListState }) {
  const {
    activeDataKnown,
    activeLinks,
    query,
    setQuery,
    filteredActiveLinks,
    activeLinksError,
    isFetchingActive,
    refetchActive,
    isLoadingActive,
    setIsModalOpen,
    copiedLinkKey,
    copyUploadLink,
    setConfirmAction,
    closeLink,
    restoreLink,
    canArchive,
    archiveLink,
    openGroupEditor,
    isClosing,
    isArchiving,
    isRestoring,
    isArchivedExpanded,
    archivedDataKnown,
    archivedLinks,
    setIsArchivedExpanded,
    archivedLinksError,
    isFetchingArchived,
    refetchArchived,
    isLoadingArchived,
    filteredArchivedLinks,
    resetPermanentDelete,
    setDeleteTarget,
    canPermanentlyDelete,
    isPermanentlyDeleting
  } = state;
  return (
    <>
      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="group-links-heading"

      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3.5 sm:px-5">
          <div>

            <h2 id="group-links-heading" className="mt-0.5 font-semibold text-slate-950">
              Live and closed group links
            </h2>
          </div>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
            {activeDataKnown ? activeLinks.length.toLocaleString() : "Unavailable"}
          </span>
        </div>

        <WorkspaceToolbar
          query={query}
          onQueryChange={setQuery}
          searchLabel="Search Group Links"
          placeholder="Search group, destination, package, or departure city"
          resultLabel={activeDataKnown ? `${filteredActiveLinks.length.toLocaleString()} active or closed` : "Live and closed links unavailable"}

        />

        {activeLinksError && (
          <WorkspaceErrorNotice>
            <p>{activeDataKnown ? "Live and closed Group Links could not be refreshed. Previously loaded links remain visible." : "Live and closed Group Links could not be loaded."}</p>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={isFetchingActive}
              onClick={() => void refetchActive()}
              className="mt-2"
            >Retry live and closed links</Button>
          </WorkspaceErrorNotice>
        )}
        {isLoadingActive ? (
          <div className="p-5"><LoadingRows /></div>
        ) : !activeDataKnown ? null : activeLinks.length === 0 ? (
          <WorkspaceEmptyState
            title="No Group Links are collecting details"
            description="Create a Group Link to collect passport images and traveller details."
            action={(
              <Button type="button" onClick={() => setIsModalOpen(true)}>
                <Link2 className="h-4 w-4" aria-hidden="true" />
                Create Group Link
              </Button>
            )}

          />
        ) : filteredActiveLinks.length === 0 ? (
          <WorkspaceEmptyState
            filtered
            title="No live or closed links match this search"
            description="Search by group, destination, package, or departure city, or clear the search to restore the full list."

          />
        ) : (
          <UploadLinkTable
            caption="Live and closed Group Links"
            links={filteredActiveLinks}
            copiedLinkKey={copiedLinkKey}
            onCopy={copyUploadLink}
            onClose={(id) => {
              setConfirmAction({
                title: "Close Group",
                description: "Clients will no longer be able to upload passports through this group link. Existing submissions remain available for review.",
                confirmLabel: "Close Group",
                onConfirm: () => closeLink(id, { onSuccess: () => setConfirmAction(null) }),
              });
            }}
            onOpen={(id) => restoreLink(id)}
            onArchive={canArchive ? (id) => {
              setConfirmAction({
                title: "Archive Group",
                description: "This group will be removed from active work. Existing passport records and uploaded images will be retained.",
                confirmLabel: "Archive Group",
                onConfirm: () => archiveLink(id, { onSuccess: () => setConfirmAction(null) }),
              });
            } : undefined}
            onRename={openGroupEditor}
            isMutating={isClosing || isArchiving || isRestoring}
            compact

          />
        )}
      </section>
      <section
        className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"
        aria-labelledby="archived-group-links-heading"

      >
        <div
          className={`flex items-center justify-between gap-3 px-4 py-3.5 sm:px-5 ${isArchivedExpanded ? "border-b border-slate-200" : ""}`}
        >
          <div>

            <h2 id="archived-group-links-heading" className="mt-0.5 font-semibold text-slate-950">
              Archived groups
            </h2>
            <p className="mt-1 text-sm text-slate-500">Groups removed from active passport queues.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
              {archivedDataKnown ? archivedLinks.length.toLocaleString() : "Unavailable"}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={isArchivedExpanded ? "Hide archived groups" : "Show archived groups"}
              aria-expanded={isArchivedExpanded}
              aria-controls="archived-group-links-content"
              onClick={() => setIsArchivedExpanded((current) => !current)}

            >
              {isArchivedExpanded ? "Hide" : "Show"}
              <ChevronDown
                className={`h-4 w-4 transition-transform motion-reduce:transition-none ${isArchivedExpanded ? "rotate-180" : ""}`}
                aria-hidden="true"

              />
            </Button>
          </div>
        </div>

        <div id="archived-group-links-content" hidden={!isArchivedExpanded}>
          {archivedLinksError && (
            <WorkspaceErrorNotice>
              <p>{archivedDataKnown ? "Archived Group Links could not be refreshed. Previously loaded links remain visible." : "Archived Group Links could not be loaded."}</p>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={isFetchingArchived}
                onClick={() => void refetchArchived()}
                className="mt-2"
              >Retry archived links</Button>
            </WorkspaceErrorNotice>
          )}
          {isLoadingArchived ? (
            <div className="p-5"><LoadingRows /></div>
          ) : !archivedDataKnown ? null : archivedLinks.length === 0 ? (
            <WorkspaceEmptyState
              title="No archived Group Links"
              description="Groups moved out of active work will remain available here according to their retention choice."

            />
          ) : filteredArchivedLinks.length === 0 ? (
            <WorkspaceEmptyState
              filtered
              title="No archived groups match this search"
              description="Clear the shared Group Link search to restore archived history."

            />
          ) : (
            <UploadLinkTable
              caption="Archived Group Links"
              links={filteredArchivedLinks}
              copiedLinkKey={copiedLinkKey}
              onCopy={copyUploadLink}
              onRestore={(id) => restoreLink(id)}
              onRename={openGroupEditor}
              onPermanentDelete={(id) => {
                resetPermanentDelete();
                setDeleteTarget(archivedLinks.find((link) => link.id === id) ?? null);
              }}
              canPermanentlyDelete={canPermanentlyDelete}
              isMutating={isRestoring || isPermanentlyDeleting}
              compact

            />
          )}
        </div>
      </section>
    </>
  );
}
