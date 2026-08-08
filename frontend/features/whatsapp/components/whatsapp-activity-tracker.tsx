"use client";

import {
  useQueries,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils/cn";
import {
  type WhatsAppActivityFailure,
  type WhatsAppActivitySummary,
  whatsappActivityApi,
} from "../api/whatsapp-activity.api";
import {
  isMissingWhatsAppBatchStatus,
  shouldRetryWhatsAppBatchStatus,
  whatsappBatchHttpStatus,
  whatsappBatchPollInterval,
} from "../utils/batch-polling";
import {
  type DisplayedWhatsAppActivity,
  initialWhatsAppActivitySummary,
  isWhatsAppBroadcastSourcePath,
  LEGACY_WHATSAPP_BATCH_STORAGE_KEY,
  parseLegacyWhatsAppBatch,
  parseTrackedWhatsAppActivities,
  type TrackedWhatsAppActivity,
  WHATSAPP_ACTIVITY_POSITION_KEY,
  WHATSAPP_ACTIVITY_STORAGE_KEY,
  whatsappActivityKey,
  whatsappActivitySourceHref,
} from "../utils/activity-tracking";

const SUCCESS_AUTO_DISMISS_MS = 12_000;
const FLOATING_EDGE_GAP = 16;
const DRAG_INTENT_THRESHOLD_PX = 4;
const DRAG_EXCLUSION_SELECTOR =
  "button, input, textarea, select, [role='button'], [data-whatsapp-activity-no-drag]";

function subscribeToClientEnvironment() {
  return () => undefined;
}

function readInitialTrackedActivities(): TrackedWhatsAppActivity[] {
  if (typeof window === "undefined") return [];
  try {
    const currentRaw = window.sessionStorage.getItem(
      WHATSAPP_ACTIVITY_STORAGE_KEY,
    );
    const current = parseTrackedWhatsAppActivities(currentRaw);
    if (currentRaw !== null) return current;
    const legacy = parseLegacyWhatsAppBatch(
      window.sessionStorage.getItem(LEGACY_WHATSAPP_BATCH_STORAGE_KEY),
    );
    return legacy ? [legacy] : [];
  } catch {
    return [];
  }
}

interface WhatsAppActivityTrackerValue {
  activities: DisplayedWhatsAppActivity[];
  registerActivity: (activity: TrackedWhatsAppActivity) => void;
  dismissActivity: (activityId: string, kind: TrackedWhatsAppActivity["kind"]) => void;
}

const WhatsAppActivityTrackerContext =
  createContext<WhatsAppActivityTrackerValue | null>(null);

export function useWhatsAppActivityTracker(): WhatsAppActivityTrackerValue {
  const context = useContext(WhatsAppActivityTrackerContext);
  if (!context) {
    throw new Error(
      "useWhatsAppActivityTracker must be used inside WhatsAppActivityTrackerProvider",
    );
  }
  return context;
}

export function WhatsAppActivityTrackerProvider({
  children,
}: {
  children: ReactNode;
}) {
  const pathname = usePathname();
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
  const refreshedTerminalActivitiesRef = useRef(new Set<string>());

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
      refreshedTerminalActivitiesRef.current.delete(key);
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

  const activityQueries = useQueries({
    queries: trackedActivities.map((activity) => ({
      queryKey: ["whatsapp", "activities", activity.kind, activity.id],
      queryFn: async () => {
        try {
          return await whatsappActivityApi.summary(activity.kind, activity.id);
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
          isMissingWhatsAppBatchStatus(
            whatsappBatchHttpStatus(query.state.error),
          )
        ) {
          return false;
        }
        return whatsappBatchPollInterval(
          query.state.data?.queued ?? activity.queued,
          activity.startedAt,
        );
      },
      refetchIntervalInBackground: true,
    })),
  });

  const activities = useMemo(
    () => {
      if (!storageReady) return [];
      return trackedActivities.map<DisplayedWhatsAppActivity>((activity, index) => {
          const query = activityQueries[index];
          const summary = query?.data ?? initialWhatsAppActivitySummary(activity);
          return {
            ...summary,
            title: activity.title,
            context_label: activity.contextLabel,
            skipped_already_sent: activity.skippedAlreadySent ?? 0,
            skipped_in_progress: activity.skippedInProgress ?? 0,
            skipped_delivery_unknown: activity.skippedDeliveryUnknown ?? 0,
            refresh_error: Boolean(query?.error),
          };
        });
    },
    [activityQueries, storageReady, trackedActivities],
  );

  useEffect(() => {
    for (const activity of activities) {
      if (activity.total <= 0 || activity.queued > 0) continue;
      const key = `${activity.kind}:${activity.activity_id}`;
      if (refreshedTerminalActivitiesRef.current.has(key)) continue;
      refreshedTerminalActivitiesRef.current.add(key);

      if (activity.kind === "broadcast") {
        void queryClient.invalidateQueries({
          queryKey: ["whatsapp", "groups"],
        });
      } else if (activity.kind === "document") {
        void queryClient.invalidateQueries({
          queryKey: ["document-distribution"],
        });
      } else {
        void queryClient.invalidateQueries({
          queryKey: [
            "operations",
            "tour-operations",
            "groups",
            activity.source_group_id,
          ],
        });
      }
    }
  }, [activities, queryClient]);

  useEffect(() => {
    const completedSuccessfully = new Set(
      activities
        .filter(
          (activity) =>
            activity.total > 0
            && activity.queued === 0
            && activity.failed === 0
            && activity.delivery_unknown === 0,
        )
        .map((activity) => `${activity.kind}:${activity.activity_id}`),
    );

    for (const [key, timer] of completionTimersRef.current) {
      if (completedSuccessfully.has(key)) continue;
      window.clearTimeout(timer);
      completionTimersRef.current.delete(key);
    }

    for (const activity of activities) {
      const key = `${activity.kind}:${activity.activity_id}`;
      if (
        !completedSuccessfully.has(key)
        || completionTimersRef.current.has(key)
      ) {
        continue;
      }
      const timer = window.setTimeout(() => {
        completionTimersRef.current.delete(key);
        dismissActivity(activity.activity_id, activity.kind);
      }, SUCCESS_AUTO_DISMISS_MS);
      completionTimersRef.current.set(key, timer);
    }
  }, [activities, dismissActivity]);

  useEffect(
    () => () => {
      for (const timer of completionTimersRef.current.values()) {
        window.clearTimeout(timer);
      }
      completionTimersRef.current.clear();
    },
    [],
  );

  const contextValue = useMemo<WhatsAppActivityTrackerValue>(
    () => ({ activities, registerActivity, dismissActivity }),
    [activities, dismissActivity, registerActivity],
  );
  const showFloatingTracker =
    storageReady
    && activities.length > 0
    && !isWhatsAppBroadcastSourcePath(pathname);

  return (
    <WhatsAppActivityTrackerContext.Provider value={contextValue}>
      {children}
      {showFloatingTracker
        ? createPortal(
            <DraggableWhatsAppActivityOverlay
              activities={activities}
              onDismiss={dismissActivity}
            />,
            document.body,
          )
        : null}
    </WhatsAppActivityTrackerContext.Provider>
  );
}

export function WhatsAppActivityInline() {
  const { activities, dismissActivity } = useWhatsAppActivityTracker();
  if (activities.length === 0) return null;

  return (
    <section
      className="overflow-hidden rounded-2xl border border-blue-200 bg-white shadow-sm"
      aria-label="Live WhatsApp delivery progress"
    >
      <div className="flex items-center gap-2 border-b border-blue-100 bg-blue-50/80 px-4 py-3">
        <MessageCircle className="h-4 w-4 text-blue-700" aria-hidden="true" />
        <h2 className="text-sm font-semibold text-slate-950">
          Live WhatsApp delivery
        </h2>
        <span className="ml-auto text-xs font-medium text-slate-500">
          {activities.length} {activities.length === 1 ? "activity" : "activities"}
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {activities.map((activity) => (
          <WhatsAppActivityRow
            key={`${activity.kind}:${activity.activity_id}`}
            activity={activity}
            variant="inline"
            onDismiss={dismissActivity}
          />
        ))}
      </div>
    </section>
  );
}

interface Position {
  x: number;
  y: number;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  originX: number;
  originY: number;
  width: number;
  height: number;
  latestX: number;
  latestY: number;
  moved: boolean;
}

function readFloatingPosition(): Position | null {
  try {
    const raw = window.localStorage.getItem(WHATSAPP_ACTIVITY_POSITION_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Position>;
    return typeof parsed.x === "number"
      && Number.isFinite(parsed.x)
      && typeof parsed.y === "number"
      && Number.isFinite(parsed.y)
      ? { x: parsed.x, y: parsed.y }
      : null;
  } catch {
    return null;
  }
}

function clampPosition(
  x: number,
  y: number,
  width: number,
  height: number,
): Position {
  return {
    x: Math.min(
      Math.max(FLOATING_EDGE_GAP, x),
      Math.max(FLOATING_EDGE_GAP, window.innerWidth - width - FLOATING_EDGE_GAP),
    ),
    y: Math.min(
      Math.max(FLOATING_EDGE_GAP, y),
      Math.max(FLOATING_EDGE_GAP, window.innerHeight - height - FLOATING_EDGE_GAP),
    ),
  };
}

function DraggableWhatsAppActivityOverlay({
  activities,
  onDismiss,
}: {
  activities: DisplayedWhatsAppActivity[];
  onDismiss: WhatsAppActivityTrackerValue["dismissActivity"];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const suppressClickAfterDragRef = useRef(false);
  const [position, setPosition] = useState<Position | null>(readFloatingPosition);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const keepInsideViewport = () => {
      setPosition((current) => {
        if (!current) return current;
        const next = clampPosition(
          current.x,
          current.y,
          container.offsetWidth,
          container.offsetHeight,
        );
        return next.x === current.x && next.y === current.y ? current : next;
      });
    };
    const observer = new ResizeObserver(keepInsideViewport);
    observer.observe(container);
    window.addEventListener("resize", keepInsideViewport);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", keepInsideViewport);
    };
  }, []);

  useEffect(() => {
    if (!position) return;
    try {
      window.localStorage.setItem(
        WHATSAPP_ACTIVITY_POSITION_KEY,
        JSON.stringify(position),
      );
    } catch {
      // Position persistence is optional; dragging still works in memory.
    }
  }, [position]);

  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const target = event.target;
    if (
      event.button !== 0
      || !(target instanceof Element)
      || target.closest(DRAG_EXCLUSION_SELECTOR)
    ) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: rect.left,
      originY: rect.top,
      width: rect.width,
      height: rect.height,
      latestX: rect.left,
      latestY: rect.top,
      moved: false,
    };
  };

  const moveDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - drag.startX;
    const deltaY = event.clientY - drag.startY;
    if (
      !drag.moved
      && Math.hypot(deltaX, deltaY) < DRAG_INTENT_THRESHOLD_PX
    ) {
      return;
    }
    if (!drag.moved) {
      drag.moved = true;
      setDragging(true);
    }
    event.preventDefault();
    const next = clampPosition(
      drag.originX + deltaX,
      drag.originY + deltaY,
      drag.width,
      drag.height,
    );
    drag.latestX = next.x;
    drag.latestY = next.y;
    const container = containerRef.current;
    if (container) {
      container.style.transform = `translate3d(${next.x - drag.originX}px, ${
        next.y - drag.originY
      }px, 0)`;
    }
  };

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragStateRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    event.currentTarget.style.transform = "";
    if (drag.moved) {
      setPosition({ x: drag.latestX, y: drag.latestY });
      suppressClickAfterDragRef.current = true;
      window.setTimeout(() => {
        suppressClickAfterDragRef.current = false;
      }, 0);
    }
    dragStateRef.current = null;
    setDragging(false);
  };

  const suppressClickAfterDrag = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (!suppressClickAfterDragRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    suppressClickAfterDragRef.current = false;
  };

  return (
    <div
      ref={containerRef}
      className={cn(
        "fixed z-[95] max-h-[calc(100vh-32px)] w-[min(420px,calc(100vw-24px))] cursor-grab select-none space-y-2 overflow-y-auto overscroll-contain active:cursor-grabbing",
        dragging && "cursor-grabbing will-change-transform",
      )}
      style={
        position
          ? { left: position.x, top: position.y }
          : { bottom: 24, right: 24 }
      }
      data-whatsapp-activity-floating
      onPointerDown={startDrag}
      onPointerMove={moveDrag}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onClickCapture={suppressClickAfterDrag}
      aria-label="Movable WhatsApp delivery progress"
    >
      {activities.map((activity) => (
        <WhatsAppActivityRow
          key={`${activity.kind}:${activity.activity_id}`}
          activity={activity}
          variant="floating"
          onDismiss={onDismiss}
        />
      ))}
    </div>
  );
}

function WhatsAppActivityRow({
  activity,
  variant,
  onDismiss,
}: {
  activity: DisplayedWhatsAppActivity;
  variant: "inline" | "floating";
  onDismiss: WhatsAppActivityTrackerValue["dismissActivity"];
}) {
  const [showFailures, setShowFailures] = useState(false);
  const failuresQuery = useQuery({
    queryKey: [
      "whatsapp",
      "activities",
      activity.kind,
      activity.activity_id,
      "failures",
    ],
    queryFn: () =>
      whatsappActivityApi.failures(activity.kind, activity.activity_id),
    enabled: showFailures && activity.failed > 0,
    refetchInterval:
      showFailures && activity.failed > 0 && activity.queued > 0
        ? 2_000
        : false,
  });
  const isRunning = activity.queued > 0;
  const completedCount = Math.max(
    0,
    activity.total - activity.queued,
  );
  const progressPercent =
    activity.total > 0
      ? Math.min(100, Math.round((completedCount / activity.total) * 100))
      : 0;
  const sourceHref = whatsappActivitySourceHref(activity);
  const skipCount =
    activity.skipped_already_sent
    + activity.skipped_in_progress
    + activity.skipped_delivery_unknown;

  return (
    <article
      className={cn(
        "text-slate-950",
        variant === "floating"
          ? "overflow-hidden rounded-[2rem] border border-emerald-200 bg-emerald-50 shadow-[0_16px_48px_rgba(6,78,59,0.20)]"
          : "bg-white px-4 py-3",
      )}
      aria-label={`${activity.title}: ${activity.sent} sent of ${activity.total}`}
    >
      <div
        className={cn(
          "flex min-w-0 items-center gap-3",
          variant === "floating" && "touch-none px-3 py-2.5",
        )}
      >
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
            isRunning
              ? "bg-blue-100 text-blue-700"
              : activity.failed > 0 || activity.delivery_unknown > 0
                ? "bg-amber-100 text-amber-700"
                : "bg-emerald-100 text-emerald-700",
          )}
        >
          {isRunning ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : activity.failed > 0 || activity.delivery_unknown > 0 ? (
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          ) : (
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
          )}
        </span>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <Link
              href={sourceHref as never}
              className="truncate text-sm font-semibold text-slate-950 hover:text-blue-700 hover:underline"
            >
              {activity.title}
            </Link>
            {activity.refresh_error ? (
              <span
                className="inline-flex shrink-0 items-center gap-1 text-[11px] font-medium text-amber-700"
                title="Live status is reconnecting"
              >
                <RefreshCw className="h-3 w-3" aria-hidden="true" />
                Reconnecting
              </span>
            ) : null}
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-2 text-xs text-slate-500">
            <span className="truncate">{activity.context_label}</span>
            <span aria-hidden="true">{"\u00b7"}</span>
            <span className="shrink-0 font-semibold tabular-nums text-slate-700">
              {activity.sent.toLocaleString()} sent of {activity.total.toLocaleString()}
            </span>
          </div>
          <div
            className={cn(
              "mt-1.5 h-1.5 overflow-hidden rounded-full",
              variant === "floating" ? "bg-emerald-100" : "bg-slate-100",
            )}
            role="progressbar"
            aria-label={`${activity.title} progress`}
            aria-valuemin={0}
            aria-valuemax={activity.total}
            aria-valuenow={completedCount}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width] duration-500 ease-out",
                activity.failed > 0 || activity.delivery_unknown > 0
                  ? "bg-amber-500"
                  : isRunning
                    ? "bg-blue-600"
                    : "bg-emerald-500",
              )}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {activity.failed > 0 ? (
          <button
            type="button"
            className="inline-flex h-8 shrink-0 items-center gap-1 rounded-full px-2 text-xs font-semibold text-red-700 hover:bg-red-50"
            aria-expanded={showFailures}
            aria-label={`${showFailures ? "Hide" : "Show"} ${activity.failed} failed recipients`}
            onClick={() => setShowFailures((current) => !current)}
          >
            {activity.failed}
            <ChevronDown
              className={cn(
                "h-4 w-4 transition-transform",
                showFailures && "rotate-180",
              )}
              aria-hidden="true"
            />
          </button>
        ) : null}

        <button
          type="button"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          aria-label={`Close ${activity.title} progress`}
          title="Hide until the next broadcast starts"
          onClick={() => onDismiss(activity.activity_id, activity.kind)}
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {skipCount > 0 ? (
        <p
          className={cn(
            "text-[11px] leading-4 text-slate-500",
            variant === "floating"
              ? "touch-none px-14 pb-2"
              : "ml-11 mt-1",
          )}
        >
          {activity.skipped_already_sent > 0
            ? `${activity.skipped_already_sent} already sent. `
            : ""}
          {activity.skipped_in_progress > 0
            ? `${activity.skipped_in_progress} already in progress. `
            : ""}
          {activity.skipped_delivery_unknown > 0
            ? `${activity.skipped_delivery_unknown} need delivery review.`
            : ""}
        </p>
      ) : null}

      {activity.delivery_unknown > 0 ? (
        <p
          className={cn(
            "text-xs font-medium text-amber-700",
            variant === "floating"
              ? "touch-none px-14 pb-2"
              : "ml-11 mt-1",
          )}
        >
          {activity.delivery_unknown} delivery outcome
          {activity.delivery_unknown === 1 ? " is" : "s are"} unknown and need review.
        </p>
      ) : null}

      {showFailures && activity.failed > 0 ? (
        <FailureRecipients
          failures={failuresQuery.data}
          loading={failuresQuery.isLoading}
          error={failuresQuery.error}
          variant={variant}
          onRetry={() => void failuresQuery.refetch()}
        />
      ) : null}
    </article>
  );
}

function FailureRecipients({
  failures,
  loading,
  error,
  variant,
  onRetry,
}: {
  failures: WhatsAppActivityFailure[] | undefined;
  loading: boolean;
  error: Error | null;
  variant: "inline" | "floating";
  onRetry: () => void;
}) {
  return (
    <div
      className={cn(
        "border-t border-red-100 bg-red-50/70",
        variant === "floating"
          ? "cursor-auto touch-pan-y select-text px-5 py-3"
          : "-mx-4 -mb-3 mt-3 px-5 py-3",
      )}
      data-whatsapp-activity-no-drag={variant === "floating" ? "" : undefined}
    >
      <p className="text-xs font-semibold uppercase tracking-wide text-red-800">
        Failed recipients
      </p>
      {loading ? (
        <p className="mt-2 text-xs text-red-700" role="status">
          Loading failed recipient names...
        </p>
      ) : error ? (
        <div className="mt-2 flex items-center justify-between gap-3 text-xs text-red-700">
          <span>Failed names could not be refreshed.</span>
          <button
            type="button"
            className="font-semibold underline"
            onClick={onRetry}
          >
            Try again
          </button>
        </div>
      ) : failures && failures.length > 0 ? (
        <ul className="mt-2 max-h-48 space-y-1.5 overflow-y-auto pr-1">
          {failures.map((failure, index) => (
            <li
              key={`${failure.phone_number}:${index}`}
              className="rounded-xl bg-white px-3 py-2 text-xs shadow-sm ring-1 ring-red-100"
            >
              <div className="flex min-w-0 items-baseline justify-between gap-3">
                <span className="truncate font-semibold text-slate-900">
                  {failure.recipient_name}
                </span>
                <span className="shrink-0 tabular-nums text-slate-500">
                  {failure.phone_number}
                </span>
              </div>
              {failure.error_message ? (
                <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-red-700">
                  {failure.error_message}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-red-700">
          No failed recipient details are available yet.
        </p>
      )}
    </div>
  );
}
