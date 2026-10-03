"use client";

import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { travelTrackerApi } from "./api";
import { trackerError } from "./model";
import type { TrackerFilters, TrackerKind, TrackerMarkRequest } from "./types";

export const trackerKeys = {
  all: ["travel-tracker"] as const,
  groups: (search: string, page: number) => ["travel-tracker", "groups", search, page] as const,
  roster: (id: string, filters: TrackerFilters) => ["travel-tracker", "roster", id, filters] as const,
};

export function useTrackerGroups(search: string, page: number) {
  return useQuery({
    queryKey: trackerKeys.groups(search, page),
    queryFn: ({ signal }) => travelTrackerApi.groups(search, page, signal),
    staleTime: 15_000,
  });
}

export function useTrackerRoster(id: string, filters: TrackerFilters) {
  return useQuery({
    queryKey: trackerKeys.roster(id, filters),
    queryFn: ({ signal }) => travelTrackerApi.roster(id, filters, signal),
    staleTime: 10_000,
    refetchInterval: 30_000,
  });
}

export function useTrackerActions(groupId: string) {
  const client = useQueryClient();
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [bulkBusy, setBulkBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ id: string; track: TrackerKind; marked: boolean } | null>(null);
  const { mutateAsync } = useMutation({ mutationFn: (request: TrackerMarkRequest) => travelTrackerApi.mark(groupId, request) });

  const mark = useCallback(async (request: TrackerMarkRequest, label: string, allowUndo = false) => {
    const single = "passenger_ids" in request && request.passenger_ids.length === 1;
    const key = single ? `${request.track}:${request.passenger_ids[0]}` : null;
    if (key) setPending((current) => ({ ...current, [key]: request.marked }));
    else setBulkBusy(true);
    setError(null);
    setNotice(null);
    setUndo(null);
    try {
      const result = await mutateAsync(request);
      setNotice(`${result.updated_count.toLocaleString()} ${result.updated_count === 1 ? "passenger" : "passengers"} updated. ${label}${result.unchanged_count ? ` ${result.unchanged_count.toLocaleString()} already had this status.` : ""}`);
      if (allowUndo && single && result.updated_count === 1 && "passenger_ids" in request) {
        setUndo({ id: request.passenger_ids[0], track: request.track, marked: !request.marked });
      }
      return result;
    } catch (reason) {
      setError(trackerError(reason));
      return null;
    } finally {
      await client.invalidateQueries({ queryKey: trackerKeys.all });
      if (key) setPending((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
      else setBulkBusy(false);
    }
  }, [client, mutateAsync]);

  const undoLast = () => {
    if (!undo) return;
    void mark({ track: undo.track, marked: undo.marked, passenger_ids: [undo.id] }, "Last change reversed.");
  };
  return { pending, bulkBusy, notice, error, undo, undoLast, mark, clearError: () => setError(null) };
}
