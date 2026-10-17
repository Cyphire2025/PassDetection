"use client";

import {
  ArrowLeft,
  ArrowUpRight,
  BellRing,
  FileText,
  MessageCircle,
  Send,
  Users,
} from "lucide-react";
import { useDeferredValue, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Skeleton } from "@/components/ui";
import { ErrorBanner } from "../components/whatsapp-dialog-ui";
import { useBroadcast } from "./broadcast-workspace-shell";
import { composerApi, type MessageDefinition } from "./composer.api";
import { BroadcastMessageComposer } from "./message-composer";
import { UpdateMessageComposer } from "./update-message-composer";
import {
  EmptyWorkspace,
  WorkspacePagination,
  WorkspaceSearch,
} from "./workspace-ui";
import styles from "./broadcast-workspace.module.css";

const icons: Record<string, typeof Send> = {
  welcome: MessageCircle,
  reminder: BellRing,
  passport_link: FileText,
  group_invite: Users,
  update: Send,
};

export function BroadcastSendPage() {
  const group = useBroadcast();
  const catalog = useQuery({
    queryKey: ["whatsapp", "message-catalog"],
    queryFn: ({ signal }) => composerApi.catalog(signal),
    staleTime: 5 * 60_000,
  });
  const [selected, setSelected] = useState<MessageDefinition | null>(null);
  const [search, setSearch] = useState("");
  const q = useDeferredValue(search).trim().toLocaleLowerCase();
  const [category, setCategory] = useState("All");
  const [offset, setOffset] = useState(0);
  const categories = [
    "All",
    ...new Set(catalog.data?.map((definition) => definition.category) ?? []),
  ];
  const matches = (catalog.data ?? []).filter(
    (definition) =>
      (category === "All" || definition.category === category) &&
      [definition.label, definition.description, definition.category].some(
        (value) => value.toLocaleLowerCase().includes(q),
      ),
  );
  if (selected)
    return (
      <div className="space-y-5">
        <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
          <ArrowLeft className="h-3.5 w-3.5" />
          Message library
        </Button>
        {selected.id === "update" ? (
          <UpdateMessageComposer />
        ) : (
          <BroadcastMessageComposer
            key={`${group.id}:${selected.id}`}
            definition={selected}
          />
        )}
      </div>
    );
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Send a message</h2>
        <p className="mt-1 text-sm text-slate-500">
          Choose a message, write the content and review who will receive it.
        </p>
      </div>
      <WorkspaceSearch
        value={search}
        onChange={(value) => {
          setSearch(value);
          setOffset(0);
        }}
        label="Search message library"
        placeholder="Find a message by name or purpose…"
      />
      <div className="flex flex-wrap gap-2" aria-label="Message categories">
        {categories.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={category === item}
            onClick={() => {
              setCategory(item);
              setOffset(0);
            }}
            className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${category === item ? "bg-slate-900 text-white" : "bg-white text-slate-500 ring-1 ring-inset ring-slate-200 hover:text-slate-900"}`}
          >
            {item}
          </button>
        ))}
      </div>
      {catalog.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((key) => (
            <Skeleton key={key} className="h-40" />
          ))}
        </div>
      ) : catalog.error ? (
        <div className="space-y-3">
          <ErrorBanner message="The message library could not be loaded." />
          <Button variant="secondary" onClick={() => void catalog.refetch()}>
            Try again
          </Button>
        </div>
      ) : matches.length === 0 ? (
        <EmptyWorkspace
          title="No matching messages"
          description="Try another name or choose a different category."
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {matches.slice(offset, offset + 18).map((definition) => {
            const Icon = icons[definition.id] ?? Send;
            return (
              <button
                type="button"
                key={definition.id}
                disabled={group.is_archived}
                onClick={() => setSelected(definition)}
                className={`${styles.surface} group flex flex-col items-start p-5 text-left transition duration-150 hover:-translate-y-0.5 hover:border-blue-300 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transform-none`}
              >
                <div className="mb-5 flex w-full items-center justify-between">
                  <span className="rounded-lg bg-blue-50 p-2 text-blue-600">
                    <Icon className="h-5 w-5" />
                  </span>
                  <ArrowUpRight className="h-4 w-4 text-slate-300 group-hover:text-blue-600" />
                </div>
                <span className="text-sm font-semibold text-slate-900">
                  {definition.label}
                </span>
                <span className="mt-2 text-xs leading-5 text-slate-500">
                  {definition.description}
                </span>
                <span className="mt-5 text-[11px] font-medium text-slate-400">
                  {definition.category}
                </span>
              </button>
            );
          })}
        </div>
      )}
      {matches.length > 18 && (
        <WorkspacePagination
          total={matches.length}
          offset={offset}
          limit={18}
          onChange={setOffset}
          label="Message library"
        />
      )}
    </div>
  );
}
