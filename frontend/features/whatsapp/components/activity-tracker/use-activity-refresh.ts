"use client";

import { useEffect, type RefObject } from "react";
import type { QueryClient } from "@tanstack/react-query";
import type { DisplayedWhatsAppActivity } from "../../utils/activity-tracking";

export function useActivityRefresh(
  activities: DisplayedWhatsAppActivity[],
  queryClient: QueryClient,
  refreshedActivityRevisionsRef: RefObject<Map<string, string>>,
) {
  useEffect(() => {
    const broadcastsToRefresh = new Set<string>();
    let refreshDocuments = false;
    const qrGroupsToRefresh = new Set<string>();
    for (const activity of activities) {
      if (activity.total <= 0) continue;
      const key = `${activity.kind}:${activity.activity_id}`;
      const revision = JSON.stringify([
        activity.queued, activity.sent, activity.failed, activity.delivery_unknown,
        activity.status_counts, activity.updated_at,
      ]);
      if (refreshedActivityRevisionsRef.current.get(key) === revision) continue;
      refreshedActivityRevisionsRef.current.set(key, revision);

      if (activity.kind === "broadcast") {
        broadcastsToRefresh.add(activity.source_group_id);
      } else if (activity.kind === "document") {
        refreshDocuments = true;
      } else {
        qrGroupsToRefresh.add(activity.source_group_id);
      }
      if (activity.failed > 0) {
        void queryClient.invalidateQueries({
          queryKey: ["whatsapp", "activities", activity.kind, activity.activity_id, "failures"],
        });
      }
    }
    if (broadcastsToRefresh.size > 0) {
      void queryClient.invalidateQueries({
        queryKey: ["whatsapp", "groups"],
        predicate: (query) => typeof query.queryKey[2] !== "string"
          || broadcastsToRefresh.has(query.queryKey[2]),
      });
    }
    if (refreshDocuments) void queryClient.invalidateQueries({ queryKey: ["document-distribution"] });
    for (const groupId of qrGroupsToRefresh) {
      void queryClient.invalidateQueries({ queryKey: ["operations", "tour-operations", "groups", groupId] });
    }
  }, [activities, queryClient, refreshedActivityRevisionsRef]);
}
