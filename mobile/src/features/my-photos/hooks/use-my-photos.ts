import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query';
import { randomUUID } from 'expo-crypto';
import { useEffect, useMemo, useRef } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { useRouteFocus } from '@/core/query/use-route-focus';

import type {
  DownloadQuality,
  MatchFeedback,
  MatchFilter,
  MyPhotosPage,
} from '../api/contracts';
import {
  acceptMyPhotosConsent,
  deleteMyPhotosEnrollment,
  prepareMyPhotosAsset,
  submitMyPhotosFeedback,
} from '../api/my-photos-api';
import {
  GalleryWindowTracker,
  MY_PHOTOS_MAX_RESIDENT_PAGES,
  myPhotosSnapshotRevisionForFilter,
  myPhotosTotalForFilter,
  type GalleryPageDirection,
} from '../data/gallery-window';
import { withMyPhotosContext } from '../data/my-photos-context';
import {
  fetchMyPhotosPage,
  fetchMyPhotosSummary,
  resolveMyPhotosPageRequestCursor,
  type CachedResult,
} from '../data/my-photos-repository';
import { FeedbackIntentLane } from './feedback-intent-lane';
import { myPhotosSummaryRefreshInterval } from './my-photos-refresh-policy';

type GalleryPageParam = Readonly<{
  cursor: string | null;
  ordinal: number;
  direction: 'forward' | 'backward';
  lookupPersistedCursor: boolean;
}>;

type GalleryQueryData = InfiniteData<CachedResult<MyPhotosPage>, GalleryPageParam>;

function usePassengerBoundary() {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  return principal?.principalType === 'passenger' && principal.passengerId
    ? {
        accountKey: principalAccountNamespace(principal),
        passengerId: principal.passengerId,
      }
    : null;
}

export function useMyPhotosSummary(tripId: string | null) {
  const boundary = usePassengerBoundary();
  const routeFocused = useRouteFocus();
  const queryKey = useMemo(
    () => ['my-photos-summary', boundary?.accountKey, boundary?.passengerId, tripId] as const,
    [boundary?.accountKey, boundary?.passengerId, tripId],
  );
  const summary = useQuery({
    queryKey,
    queryFn: ({ signal }) => withMyPhotosContext(
      tripId!,
      signal,
      (context, assertActive) => fetchMyPhotosSummary(context, assertActive),
    ),
    enabled: Boolean(boundary && tripId),
    staleTime: 15_000,
    refetchInterval: (query) => myPhotosSummaryRefreshInterval({
      routeFocused,
      experienceState: query.state.data?.value.experience_state ?? null,
      searchStatus: query.state.data?.value.search?.status ?? null,
      failureCount: query.state.fetchFailureCount,
      error: query.state.error,
    }),
    refetchIntervalInBackground: false,
  });
  return summary;
}

export function useMyPhotosGallery(
  tripId: string | null,
  filter: MatchFilter,
  summary: ReturnType<typeof useMyPhotosSummary>['data'],
  consumer: 'grid' | 'viewer' = 'grid',
) {
  const boundary = usePassengerBoundary();
  const queryClient = useQueryClient();
  const revision = summary
    ? myPhotosSnapshotRevisionForFilter(summary.value, filter)
    : 0;
  const totalCount = myPhotosTotalForFilter(summary?.value ?? null, filter);
  const queryKey = useMemo(
    () => [
      'my-photos-gallery', boundary?.accountKey, boundary?.passengerId,
      tripId, revision, filter, consumer,
    ] as const,
    [boundary?.accountKey, boundary?.passengerId, consumer, filter, revision, tripId],
  );
  const gridQueryKey = useMemo(
    () => [
      'my-photos-gallery', boundary?.accountKey, boundary?.passengerId,
      tripId, revision, filter, 'grid',
    ] as const,
    [boundary?.accountKey, boundary?.passengerId, filter, revision, tripId],
  );
  const viewerSeed = consumer === 'viewer'
    ? queryClient.getQueryData<GalleryQueryData>(gridQueryKey)
    : undefined;
  const tracker = useMemo(
    () => new GalleryWindowTracker(
      viewerSeed?.pages.map((page) => page.value) ?? [],
      viewerSeed?.pageParams.map((page) => page.cursor) ?? [],
    ),
    [viewerSeed],
  );
  const query = useInfiniteQuery({
    queryKey,
    ...(viewerSeed ? { initialData: viewerSeed } : {}),
    queryFn: ({ pageParam, signal }) => withMyPhotosContext(
      tripId!,
      signal,
      async (context, assertActive) => {
        const resolved = await resolveMyPhotosPageRequestCursor(
          context,
          filter,
          revision,
          pageParam.ordinal,
          pageParam.cursor,
          pageParam.lookupPersistedCursor,
        );
        assertActive();
        const direction: GalleryPageDirection = pageParam.direction === 'backward'
          ? 'backward'
          : resolved.revisit
            ? 'revisit'
            : 'forward';
        if (pageParam.ordinal === 0 && pageParam.direction === 'forward') tracker.reset();
        const result = await fetchMyPhotosPage(
          context,
          filter,
          resolved.cursor,
          pageParam.ordinal,
          revision,
          totalCount,
          assertActive,
          direction,
          (page) => tracker.preview(page, resolved.cursor, direction),
        );
        assertActive();
        if (result.source === 'network') tracker.commit(result.value, resolved.cursor, direction);
        return result;
      },
    ),
    initialPageParam: {
      cursor: null,
      ordinal: 0,
      direction: 'forward',
      lookupPersistedCursor: false,
    } as GalleryPageParam,
    getNextPageParam: (lastPage, _pages, lastPageParam): GalleryPageParam | undefined => (
      lastPage.source === 'network' && lastPage.value.next_cursor
        ? {
            cursor: lastPage.value.next_cursor,
            ordinal: lastPageParam.ordinal + 1,
            direction: 'forward',
            lookupPersistedCursor: false,
          }
        : undefined
    ),
    getPreviousPageParam: (_firstPage, _pages, firstPageParam): GalleryPageParam | undefined => (
      firstPageParam.ordinal > 0
        ? {
            cursor: null,
            ordinal: firstPageParam.ordinal - 1,
            direction: 'backward',
            lookupPersistedCursor: true,
          }
        : undefined
    ),
    maxPages: MY_PHOTOS_MAX_RESIDENT_PAGES,
    enabled: Boolean(
      boundary
      && tripId
      && summary
      && (
        ['matches_ready', 'matches_preparing', 'offline_results', 'partial_offline_results']
          .includes(summary.value.experience_state)
        || (
          ['search_queued', 'searching'].includes(summary.value.experience_state)
          && summary.value.results.match_count > 0
        )
        || (
          summary.value.experience_state === 'enrollment_deleted'
          && summary.value.results.match_count > 0
        )
        || (
          summary.value.experience_state === 'no_matches'
          && filter === 'all'
          && summary.value.gallery.all_group_photos_enabled
        )
      )
      && (filter !== 'all' || summary.value.gallery.all_group_photos_enabled)
    ),
    staleTime: 30_000,
  });
  const residentPageParams = query.data?.pageParams as readonly GalleryPageParam[] | undefined;
  const firstResidentPageOrdinal = residentPageParams?.[0]?.ordinal ?? 0;
  return {
    ...query,
    firstResidentPageOrdinal,
    residentStartIndex: firstResidentPageOrdinal * 48,
  } as const;
}

export function useMyPhotosMutations(tripId: string | null) {
  const queryClient = useQueryClient();
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const requestKeys = useRef(new Map<string, string>());
  const feedbackIntents = useRef(new FeedbackIntentLane());
  const owner = principal ? principalAccountNamespace(principal) : null;
  useEffect(() => {
    requestKeys.current.clear();
    feedbackIntents.current.reset();
  }, [owner, principal?.id, tripId]);
  const requestId = (identity: string): string => {
    const existing = requestKeys.current.get(identity);
    if (existing) return existing;
    const created = randomUUID();
    requestKeys.current.set(identity, created);
    return created;
  };
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['my-photos-summary'] });
  const consent = useMutation({
    mutationFn: (version: string) => withMyPhotosContext(
      tripId!,
      new AbortController().signal,
      (context) => acceptMyPhotosConsent(
        context.tripId,
        version,
        context.signal,
        requestId(`consent:${version}`),
      ),
    ),
    onSuccess: (_response, version) => {
      requestKeys.current.delete(`consent:${version}`);
      void invalidate();
    },
  });
  const feedback = useMutation({
    mutationFn: async (input: Readonly<{
      assetId: string;
      feedback: Exclude<MatchFeedback, 'none'>;
    }>) => feedbackIntents.current.run(input.assetId, async (revision) => {
      const identity = `feedback:${input.assetId}:${revision}`;
      try {
        return await withMyPhotosContext(
          tripId!,
          new AbortController().signal,
          (context) => submitMyPhotosFeedback(
            context.tripId,
            input.assetId,
            input.feedback,
            context.signal,
            requestId(identity),
          ),
        );
      } finally {
        requestKeys.current.delete(identity);
      }
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['my-photos-gallery'] });
    },
  });
  const prepare = useMutation({
    mutationFn: (input: Readonly<{ assetId: string; quality: DownloadQuality }>) => (
      withMyPhotosContext(
        tripId!,
        new AbortController().signal,
        (context) => prepareMyPhotosAsset(
          context.tripId, input.assetId, input.quality, context.signal,
          requestId(`prepare:${input.assetId}:${input.quality}`),
        ),
      )
    ),
    onSuccess: (response, input) => {
      if (response.state === 'delivery_available') {
        requestKeys.current.delete(`prepare:${input.assetId}:${input.quality}`);
      }
      void invalidate();
    },
  });
  const deleteEnrollment = useMutation({
    mutationFn: (scope: 'enrollment_only' | 'enrollment_and_search_data') => (
      withMyPhotosContext(
        tripId!,
        new AbortController().signal,
        (context) => deleteMyPhotosEnrollment(
          context.tripId,
          scope,
          context.signal,
          requestId(`delete:${scope}`),
        ),
      )
    ),
    onSuccess: (response, scope) => {
      if (response.provider_deletion_status === 'complete' || response.provider_deletion_status === 'not_required') {
        requestKeys.current.delete(`delete:${scope}`);
      }
      void invalidate();
    },
  });
  return { consent, feedback, prepare, deleteEnrollment };
}
