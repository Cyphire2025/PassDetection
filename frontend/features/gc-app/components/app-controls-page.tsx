"use client";

import { Plus, Search, Smartphone } from "lucide-react";
import { useState } from "react";
import { Button, Card, CardContent, Input } from "@/components/ui";
import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { canArchiveGroup } from "@/lib/utils/role-access";
import { selectUser, useAuthStore } from "@/stores/auth.store";
import { useDebounce } from "@/hooks/use-debounce";
import { GC_APP_DEFAULT_PAGE_SIZE } from "../api/gc-app-admin.api";
import { APP_AVAILABILITY_OPTIONS } from "../availability";
import { useGcAppGroups } from "../hooks/use-gc-app-admin";
import { useGcGroupPicker } from "../hooks/use-gc-group-picker";
import { AddGcAppGroupDialog } from "./add-gc-app-group-dialog";
import type { GcAppAvailability, GcAppGroupControl } from "../types";
import { GcAlert, GcLoadingRows, GcPagination } from "./gc-app-feedback";
import { useGcAppAgencyScope } from "./gc-app-agency-scope";
import { GcSelect } from "./gc-select";
import { GroupControlCard } from "./group-control-card";
import { RemoveAppGroupDialog } from "./remove-app-group-dialog";

export function AppControlsPage() {
  const { agencyId } = useGcAppAgencyScope();
  return <AppControlsWorkspace key={agencyId} agencyId={agencyId} />;
}

function AppControlsWorkspace({ agencyId }: { agencyId: string | null }) {
  const canRemove = canArchiveGroup(useAuthStore(selectUser)?.role);
  const [pendingRemoval, setPendingRemoval] = useState<GcAppGroupControl | null>(null);
  const [removalMessage, setRemovalMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [availability, setAvailability] = useState<GcAppAvailability | "all">("all");
  const [page, setPage] = useState(1);
  const picker = useGcGroupPicker(agencyId);
  const { openPicker } = picker;
  const debouncedSearch = useDebounce(search, 300);
  const filters = { page, page_size: GC_APP_DEFAULT_PAGE_SIZE, search: debouncedSearch, availability } as const;
  const groups = useGcAppGroups(agencyId, filters);

  return (
    <div className="space-y-5">
      <PageHeader
        title="App Controls"
        description="Manage GC App one trip at a time: availability, people, documents, and announcements. Paused trips stay here so you can restore them."
        actions={(
          <Button type="button" leftIcon={<Plus className="h-4 w-4" />} onClick={openPicker}>
            Add group to GC App
          </Button>
        )}
      />

      <Card className="overflow-visible border-slate-200/80 shadow-[0_8px_30px_-24px_rgba(15,23,42,0.45)]">
        <CardContent className="grid gap-3 p-4 sm:p-5 md:grid-cols-[minmax(0,1fr)_18rem] md:items-end">
          <Input
            label="Search GC App trips"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="Group name or destination"
            leftAddon={<Search className="h-4 w-4" aria-hidden="true" />}
          />
          <GcSelect
            id="gc-group-availability"
            label="App availability"
            value={availability}
            options={APP_AVAILABILITY_OPTIONS}
            onChange={(nextAvailability) => {
              setAvailability(nextAvailability as GcAppAvailability | "all");
              setPage(1);
            }}
          />
        </CardContent>
      </Card>

      {removalMessage && <GcAlert tone="success" message={removalMessage} />}
      {groups.isError && groups.data && <GcAlert message="The trip list could not be refreshed. The last loaded data is shown; refresh before making changes." />}
      {groups.isLoading ? (
        <Card><GcLoadingRows count={3} /></Card>
      ) : groups.isError && !groups.data ? (
        <Card><CardContent className="space-y-3 p-5"><GcAlert message="GC App groups could not be loaded." /><Button type="button" variant="secondary" size="sm" onClick={() => void groups.refetch()}>Retry</Button></CardContent></Card>
      ) : groups.data?.items.length === 0 ? (
        <EmptyState
          icon={<Smartphone className="h-5 w-5" aria-hidden="true" />}
          title={page > 1 ? "No trips on this page" : "No GC App trips found"}
          description={page > 1 ? "The trip list has changed. Return to the previous page to see the remaining trips." : search || availability !== "all" ? "Adjust the search or app availability filter." : "Add a passport group to set up its trip in GC App. Its collection link can be open or closed."}
          action={page > 1 ? { label: "Previous page", onClick: () => setPage(page - 1) } : !search && availability === "all" ? { label: "Add group to GC App", onClick: openPicker } : undefined}
        />
      ) : (
        <div className="space-y-4">
          {groups.data?.items.map((group) => (
            <GroupControlCard
              key={group.id}
              group={group}
              removalDisabled={groups.isFetching || groups.isError}
              onRemove={canRemove && agencyId ? () => { setRemovalMessage(null); setPendingRemoval(group); } : undefined}
            />
          ))}
          {groups.data && (
            <Card>
              <GcPagination
                page={groups.data.page}
                total={groups.data.total}
                pageSize={groups.data.page_size}
                hasNext={groups.data.has_next}
                disabled={groups.isFetching}
                onPageChange={setPage}
              />
            </Card>
          )}
        </div>
      )}

      {pendingRemoval && agencyId && canRemove && <RemoveAppGroupDialog
        key={`${agencyId}:${pendingRemoval.id}`} agencyId={agencyId} group={pendingRemoval}
        onClose={() => setPendingRemoval(null)}
        onRemoved={() => {
          setRemovalMessage(`${pendingRemoval.name} was removed from GC App. The original group and its records are kept.`);
          setPendingRemoval(null);
          const stillListed = groups.data?.items.some((item) => item.id === pendingRemoval.id);
          const remaining = Math.max(0, (groups.data?.total ?? 0) - (stillListed ? 1 : 0));
          setPage((current) => Math.min(current, Math.max(1, Math.ceil(remaining / GC_APP_DEFAULT_PAGE_SIZE))));
          void groups.refetch();
        }}
      />}

      <AddGcAppGroupDialog picker={picker} />
    </div>
  );
}
