"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQueries, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { whatsappActivityApi, type WhatsAppActivitySummary } from "../../api/whatsapp-activity.api";
import {
  documentActivityPollInterval, isMissingWhatsAppBatchStatus, isTerminalWhatsAppBatchStatus,
  shouldRetryWhatsAppBatchStatus, whatsappBatchHttpStatus, whatsappActivityPollInterval,
} from "../../utils/batch-polling";
import {
  type DisplayedWhatsAppActivity, type TrackedWhatsAppActivity,
  initialWhatsAppActivitySummary, whatsappActivityKey,
  LEGACY_WHATSAPP_BATCH_STORAGE_KEY, WHATSAPP_ACTIVITY_STORAGE_KEY,
} from "../../utils/activity-tracking";
import type { WhatsAppActivityTrackerValue } from "./context";
import { subscribeToClientEnvironment, readInitialTrackedActivities } from "./storage";
import { useActivityRefresh } from "./use-activity-refresh";
import { useActivityCompletion } from "./use-activity-completion";

export function useTrackedActivities() {
  const queryClient = useQueryClient();

  const storageReady = useSyncExternalStore(
    subscribeToClientEnvironment,
    () => true,
    () => false,
  );

  const [trackedActivities, setTrackedActivities] = useState<
    TrackedWhatsAppActivity[]
  >(readInitialTrackedActivities);

  const completionTimersRef = useRef(new Map<string, number>());

  const refreshedActivityRevisionsRef = useRef(new Map<string, string>());

  useEffect(() => {
    if (!storageReady) return;
    try {
      window.sessionStorage.setItem(
        WHATSAPP_ACTIVITY_STORAGE_KEY,
        JSON.stringify(trackedActivities),
      );
      window.sessionStorage.removeItem(LEGACY_WHATSAPP_BATCH_STORAGE_KEY);
    } catch {
      // Live in-memory tracking remains available when browser storage is denied.
    }
  }, [storageReady, trackedActivities]);

  const registerActivity = useCallback(
    (activity: TrackedWhatsAppActivity) => {
      const key = whatsappActivityKey(activity);
      const completionTimer = completionTimersRef.current.get(key);
      if (completionTimer !== undefined) {
        window.clearTimeout(completionTimer);
        completionTimersRef.current.delete(key);
      }
      refreshedActivityRevisionsRef.current.delete(key);
      setTrackedActivities((current) => [
        activity,
        ...current.filter((candidate) => whatsappActivityKey(candidate) !== key),
      ]);
    },
    [],
  );

  const dismissActivity = useCallback(
    (activityId: string, kind: TrackedWhatsAppActivity["kind"]) => {
      const key = `${kind}:${activityId}`;
      refreshedActivityRevisionsRef.current.delete(key);
      const completionTimer = completionTimersRef.current.get(key);
      if (completionTimer !== undefined) {
        window.clearTimeout(completionTimer);
        completionTimersRef.current.delete(key);
      }
      setTrackedActivities((current) =>
        current.filter(
          (candidate) => whatsappActivityKey(candidate) !== key,
        ),
      );
      queryClient.removeQueries({
        queryKey: ["whatsapp", "activities", kind, activityId],
      });
    },
    [queryClient],
  );

  const combineActivities = useCallback(
    (queries: UseQueryResult<WhatsAppActivitySummary>[]): DisplayedWhatsAppActivity[] => {
      if (!storageReady) return [];
      return trackedActivities.map((activity, index) => {
        const query = queries[index];
        const summary = query?.data ?? initialWhatsAppActivitySummary(activity);
        return {
          ...summary,
          title: activity.title,
          context_label: activity.contextLabel,
          messageType: activity.messageType,
          startedAt: activity.startedAt,
          skipped_already_sent: activity.skippedAlreadySent ?? 0,
          skipped_in_progress: activity.skippedInProgress ?? 0,
          skipped_delivery_unknown: activity.skippedDeliveryUnknown ?? 0,
          refresh_error: Boolean(query?.error),
        };
      });
    },
    [storageReady, trackedActivities],
  );

  const activityQueryOptions = useMemo(
    () => trackedActivities.map((activity) => ({
      queryKey: ["whatsapp", "activities", activity.kind, activity.id],
      queryFn: async ({ signal }: { signal: AbortSignal }) => {
        try {
          return await whatsappActivityApi.summary(activity.kind, activity.id, signal);
        } catch (error) {
          if (
            isMissingWhatsAppBatchStatus(whatsappBatchHttpStatus(error))
          ) {
            const missingKey = whatsappActivityKey(activity);
            setTrackedActivities((current) =>
              current.filter(
                (candidate) => whatsappActivityKey(candidate) !== missingKey,
              ),
            );
          }
          throw error;
        }
      },
      enabled: storageReady,
      retry: (failureCount: number, error: unknown) =>
        shouldRetryWhatsAppBatchStatus(
          failureCount,
          whatsappBatchHttpStatus(error),
        ),
      refetchInterval: (query: {
        state: { data?: WhatsAppActivitySummary; error?: unknown };
      }) => {
        if (
          isTerminalWhatsAppBatchStatus(
            whatsappBatchHttpStatus(query.state.error),
          )
        ) {
          return false;
        }
        if (activity.kind === "document") {
          return documentActivityPollInterval(
            query.state.data?.queued ?? activity.queued,
            query.state.data?.status_counts,
            activity.startedAt,
          );
        }
        return whatsappActivityPollInterval(
          query.state.data?.queued ?? activity.queued,
          query.state.data?.status_counts,
          query.state.data ? Date.parse(query.state.data.updated_at) : activity.startedAt,
          query.state.data?.sent ?? activity.sent,
          query.state.data?.delivery_unknown ?? activity.deliveryUnknown,
        );
      },
      refetchIntervalInBackground: false,
      refetchOnWindowFocus: "always" as const,
      refetchOnReconnect: "always" as const,
    })),
    [storageReady, trackedActivities],
  );

  const activities = useQueries({
    queries: activityQueryOptions,
    // Query combines preserve equal objects, so polling the same server state
    // does not refresh every workspace subscribed to the activity context.
    combine: combineActivities,
  });

  useActivityRefresh(activities, queryClient, refreshedActivityRevisionsRef);

  useActivityCompletion(activities, dismissActivity, completionTimersRef);

  const contextValue = useMemo<WhatsAppActivityTrackerValue>(
    () => ({ activities, registerActivity, dismissActivity }),
    [activities, dismissActivity, registerActivity],
  );

  return { contextValue, storageReady };
}
