"use client";

import { ROUTES } from "@/constants/routes";
import {
  Archive,
  ArrowUpRight,
  MessageCircle,
  Plus,
  RotateCcw,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";
import { Button, Skeleton } from "@/components/ui";
import {
  useCreateWhatsAppGroup,
  useRestoreWhatsAppGroup,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";
import { CreateBroadcastDialog } from "../components/whatsapp-create-broadcast-dialog";
import {
  ErrorBanner,
  readErrorMessage,
} from "../components/whatsapp-dialog-ui";
import {
  EmptyWorkspace,
  tableClass,
  WorkspacePagination,
  WorkspaceSearch,
  workspaceDate,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

export function BroadcastIndex() {
  const [archived, setArchived] = useState(false);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const deferredSearch = useDeferredValue(search).trim().toLocaleLowerCase();
  const active = useWhatsAppGroups();
  const archive = useWhatsAppGroups(true);
  const create = useCreateWhatsAppGroup();
  const restore = useRestoreWhatsAppGroup();
  const source = archived ? archive : active;
  const groups = (source.data ?? []).filter((group) =>
    group.name.toLocaleLowerCase().includes(deferredSearch),
  );
  const pageOffset = Math.min(
    offset,
    Math.max(0, Math.ceil(groups.length / 20) - 1) * 20,
  );
  return (
    <div className={`${styles.enter} space-y-7`}>
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-500">
            <MessageCircle className="h-4 w-4 text-blue-600" />
            Communications
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-950">
            WhatsApp broadcasts
          </h1>
          <p className="mt-1.5 text-sm text-slate-500">
            Open a broadcast to send messages, track delivery and manage your
            recipients.
          </p>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus className="h-4 w-4" />
          Create broadcast
        </Button>
      </header>
      <section className={styles.surface}>
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 px-5 pt-1">
          <nav aria-label="Broadcast lists" className="flex gap-6">
            {[
              { value: false, label: "Active", count: active.data?.length },
              { value: true, label: "Archived", count: archive.data?.length },
            ].map((tab) => (
              <button
                key={tab.label}
                onClick={() => {
                  setArchived(tab.value);
                  setOffset(0);
                }}
                aria-current={archived === tab.value ? "page" : undefined}
                className={`flex items-center gap-2 border-b-2 py-4 text-sm font-medium transition-colors ${archived === tab.value ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-900"}`}
              >
                {tab.value && <Archive className="h-4 w-4" />}
                {tab.label}
                <span className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs tabular-nums text-slate-500">
                  {tab.count ?? "—"}
                </span>
              </button>
            ))}
          </nav>
          <p className="text-xs text-slate-400">
            Each broadcast has its own workspace
          </p>
        </div>
        <div className="p-5">
          <WorkspaceSearch
            value={search}
            onChange={(value) => {
              setSearch(value);
              setOffset(0);
            }}
            label="Search broadcasts"
            placeholder="Search broadcasts by name…"
          />
        </div>
        {actionError && (
          <div className="px-5 pb-4">
            <ErrorBanner message={actionError} />
          </div>
        )}
        {source.error ? (
          <div className="p-5">
            <ErrorBanner message="Broadcasts could not be loaded." />
            <Button
              className="mt-3"
              variant="secondary"
              onClick={() => void source.refetch()}
            >
              Try again
            </Button>
          </div>
        ) : source.isLoading ? (
          <div className="space-y-3 p-5">
            {[1, 2, 3].map((key) => (
              <Skeleton key={key} className="h-20" />
            ))}
          </div>
        ) : groups.length === 0 ? (
          <EmptyWorkspace
            title={
              search
                ? "No broadcasts found"
                : archived
                  ? "No archived broadcasts"
                  : "Your broadcasts will appear here"
            }
            description={
              search
                ? "Try another name or switch between Active and Archived."
                : archived
                  ? "Archived broadcasts retain their recipients and message history."
                  : "Create a broadcast to organise recipients and start messaging."
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className={tableClass}>
                <thead>
                  <tr>
                    <th>Broadcast</th>
                    <th>Recipients</th>
                    <th>Last updated</th>
                    <th>
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {groups.slice(pageOffset, pageOffset + 20).map((group) => (
                    <tr key={group.id}>
                      <td>
                        <Link
                          className="font-medium text-slate-900 hover:text-blue-700"
                          href={ROUTES.dashboard.whatsappBroadcast(group.id)}
                        >
                          {group.name}
                        </Link>
                        {group.total_contact_count > group.recipient_count && (
                          <p className="mt-1 text-xs text-slate-500">
                            {group.total_contact_count.toLocaleString()} contact
                            records
                          </p>
                        )}
                      </td>
                      <td>
                        <span className="inline-flex items-center gap-2 text-slate-600">
                          <Users className="h-4 w-4 text-slate-400" />
                          {group.recipient_count.toLocaleString()}
                        </span>
                      </td>
                      <td className="whitespace-nowrap text-xs text-slate-500">
                        {workspaceDate(group.updated_at)}
                      </td>
                      <td>
                        <div className="flex justify-end gap-3">
                          {archived && (
                            <Button
                              variant="ghost"
                              disabled={restore.isPending}
                              onClick={() => {
                                setActionError(null);
                                restore.mutate(group.id, {
                                  onError: (error) =>
                                    setActionError(
                                      readErrorMessage(
                                        error,
                                        "Could not restore broadcast.",
                                      ),
                                    ),
                                });
                              }}
                            >
                              <RotateCcw className="h-3.5 w-3.5" />
                              Restore
                            </Button>
                          )}
                          <Link
                            aria-label={`Open ${group.name}`}
                            className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 focus-visible:outline-blue-500"
                            href={ROUTES.dashboard.whatsappBroadcast(group.id)}
                          >
                            Open broadcast
                            <ArrowUpRight className="h-3.5 w-3.5" />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <WorkspacePagination
              total={groups.length}
              offset={pageOffset}
              limit={20}
              onChange={setOffset}
              label="Broadcasts"
            />
          </>
        )}
      </section>
      {creating && (
        <CreateBroadcastDialog
          isLoading={create.isPending}
          onClose={() => setCreating(false)}
          onSubmit={async (payload) => {
            await create.mutateAsync(payload);
            setCreating(false);
          }}
        />
      )}
    </div>
  );
}
