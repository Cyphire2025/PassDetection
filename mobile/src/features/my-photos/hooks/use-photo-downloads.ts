import NetInfo from '@react-native-community/netinfo';
import {
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { useCallback, useMemo } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';

import type {
  DownloadQuality,
  MyPhotosAsset,
  MyPhotosSummary,
} from '../api/contracts';
import {
  captureMyPhotosContext,
  withMyPhotosContext,
  type MyPhotosContext,
} from '../data/my-photos-context';
import {
  activatePhotoDownloadPlan,
  cancelPhotoDownload,
  clearMyPhotosStorage,
  openLocalPhoto,
  pausePhotoDownload,
  planAllMatchedPhotoDownloads,
  planFilterPhotoDownloads,
  planSelectedPhotoDownloads,
  recoverAndReconcilePhotoDownloads,
  removeAllCompletedPhotoDownloads,
  removeDownloadedPhoto,
  resumePhotoDownload,
  type LocalPhotoLease,
  type PhotoDownloadPlan,
} from '../downloads/download-manager';
import {
  beginPhotoDownloadNamespaceOperation,
  requestPhotoDownloadDrain,
  withExclusivePhotoDownloadNamespaceOperation,
  withPhotoDownloadNamespaceOperation,
} from '../downloads/photo-download-runtime';
import {
  getPhotoDownload,
  listCompletedPhotoDownloadsPage,
  listPhotoDownloads,
  photoDownloadStorageSummary,
  type CompletedPhotoDownloadCursor,
} from '../downloads/download-repository';

type PlanRequest = Readonly<
  | { kind: 'selected'; assets: readonly MyPhotosAsset[]; galleryRevision: number }
  | {
      kind: 'filter_selection';
      summary: MyPhotosSummary;
      filter: 'best' | 'possible';
      excludedAssetIds: readonly string[];
    }
  | { kind: 'all_matched'; summary: MyPhotosSummary }
>;

export type PhotoDownloadPlanView = Readonly<{
  id: string;
  itemCount: number;
  qualities: readonly DownloadQuality[];
  estimatedBytes: Readonly<Partial<Record<DownloadQuality, number>>>;
  canStart: Readonly<Partial<Record<DownloadQuality, boolean>>>;
  availableDeviceBytes: number;
  substantial: Readonly<Partial<Record<DownloadQuality, boolean>>>;
}>;

export function photoDownloadPlanView(plan: PhotoDownloadPlan): PhotoDownloadPlanView {
  return {
    id: plan.id,
    itemCount: plan.itemCount,
    qualities: plan.supportedQualities,
    estimatedBytes: plan.estimatedBytesByQuality,
    canStart: plan.canStartByQuality,
    availableDeviceBytes: plan.availableDiskBytes,
    substantial: plan.substantialByQuality,
  };
}

function networkState(state: Awaited<ReturnType<typeof NetInfo.fetch>>) {
  return {
    connected: Boolean(state.isConnected && state.isInternetReachable !== false),
    wifi: state.type === 'wifi',
  } as const;
}

function withFencedPhotoDownloadContext<T>(
  tripId: string,
  signal: AbortSignal,
  operation: (context: MyPhotosContext) => T | Promise<T>,
): Promise<T> {
  return withMyPhotosContext(tripId, signal, (context) => (
    withPhotoDownloadNamespaceOperation(
      context,
      context.signal,
      (fencedSignal) => Promise.resolve(operation({ ...context, signal: fencedSignal })),
    )
  ));
}

export function usePhotoDownloads(tripId: string | null) {
  const queryClient = useQueryClient();
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const boundary = principal?.principalType === 'passenger' && principal.passengerId
    ? {
        namespace: principalAccountNamespace(principal),
        passengerId: principal.passengerId,
      }
    : null;
  const ownerKey = useMemo(
    () => [boundary?.namespace, boundary?.passengerId, tripId] as const,
    [boundary?.namespace, boundary?.passengerId, tripId],
  );
  const jobsKey = useMemo(() => ['my-photos-downloads', ...ownerKey] as const, [ownerKey]);
  const summaryKey = useMemo(() => ['my-photos-download-storage', ...ownerKey] as const, [ownerKey]);
  const completedKey = useMemo(() => ['my-photos-completed-downloads', ...ownerKey] as const, [ownerKey]);
  const ownedJobKey = useMemo(() => ['my-photos-download', ...ownerKey] as const, [ownerKey]);
  const invalidate = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: jobsKey }),
      queryClient.invalidateQueries({ queryKey: summaryKey }),
      queryClient.invalidateQueries({ queryKey: completedKey }),
      queryClient.invalidateQueries({ queryKey: ownedJobKey }),
    ]);
  }, [completedKey, jobsKey, ownedJobKey, queryClient, summaryKey]);

  const jobs = useQuery({
    queryKey: jobsKey,
    queryFn: ({ signal }) => withFencedPhotoDownloadContext(
      tripId!,
      signal,
      (context) => listPhotoDownloads(context, false, 500),
    ),
    enabled: Boolean(boundary && tripId),
    staleTime: 1_000,
  });
  const storage = useQuery({
    queryKey: summaryKey,
    queryFn: ({ signal }) => withFencedPhotoDownloadContext(
      tripId!,
      signal,
      (context) => photoDownloadStorageSummary(context),
    ),
    enabled: Boolean(boundary && tripId),
    staleTime: 1_000,
  });

  const plan = useMutation({
    mutationFn: (request: PlanRequest) => withFencedPhotoDownloadContext(
      tripId!,
      new AbortController().signal,
      (context) => {
        if (request.kind === 'all_matched') {
          return planAllMatchedPhotoDownloads(context, request.summary);
        }
        if (request.kind === 'filter_selection') {
          return planFilterPhotoDownloads(
            context,
            request.summary,
            request.filter,
            request.excludedAssetIds,
            context.signal,
          );
        }
        return planSelectedPhotoDownloads(context, request.assets, request.galleryRevision);
      },
    ),
  });
  const activate = useMutation({
    mutationFn: (input: Readonly<{
      plan: PhotoDownloadPlan;
      quality: DownloadQuality;
      wifiOnly: boolean;
    }>) => withFencedPhotoDownloadContext(
      tripId!,
      new AbortController().signal,
      async (context) => {
        const result = await activatePhotoDownloadPlan(
          context,
          input.plan,
          input.quality,
          input.wifiOnly,
        );
        requestPhotoDownloadDrain();
        return result;
      },
    ),
    onSettled: () => { void invalidate(); },
  });
  const control = useMutation({
    mutationFn: (input: Readonly<{
      action: 'pause' | 'resume' | 'cancel' | 'remove';
      jobId: string;
    }>) => withFencedPhotoDownloadContext(
      tripId!,
      new AbortController().signal,
      async (context) => {
        if (input.action === 'pause') return pausePhotoDownload(context, input.jobId);
        if (input.action === 'resume') {
          await resumePhotoDownload(context, input.jobId);
          requestPhotoDownloadDrain();
          return;
        }
        if (input.action === 'cancel') return cancelPhotoDownload(context, input.jobId);
        return removeDownloadedPhoto(context, input.jobId);
      },
    ),
    onSettled: () => { void invalidate(); },
  });
  const reconcile = useMutation({
    mutationFn: () => withFencedPhotoDownloadContext(
      tripId!,
      new AbortController().signal,
      async (context) => recoverAndReconcilePhotoDownloads(
        context,
        networkState(await NetInfo.fetch()),
        context.signal,
      ),
    ),
    onSettled: () => { void invalidate(); },
  });
  const removeAll = useMutation({
    mutationFn: () => withFencedPhotoDownloadContext(
      tripId!,
      new AbortController().signal,
      (context) => removeAllCompletedPhotoDownloads(context, context.signal),
    ),
    onSettled: () => { void invalidate(); },
  });
  const clearStorage = useMutation({
    mutationFn: () => withMyPhotosContext(
      tripId!,
      new AbortController().signal,
      (context) => withExclusivePhotoDownloadNamespaceOperation(
        context,
        context.signal,
        (signal) => clearMyPhotosStorage({ ...context, signal }, signal),
      ),
    ),
    onSettled: () => {
      requestPhotoDownloadDrain();
      void invalidate();
    },
  });
  const planAsync = plan.mutateAsync;
  const activateAsync = activate.mutateAsync;
  const controlAsync = control.mutateAsync;
  const removeAllAsync = removeAll.mutateAsync;
  const clearStorageAsync = clearStorage.mutateAsync;

  const openLocal = useCallback((
    assetId: string,
    quality: DownloadQuality,
    signal?: AbortSignal,
  ): Promise<LocalPhotoLease | null> => {
    const operation = async (): Promise<LocalPhotoLease | null> => {
      const contextLease = captureMyPhotosContext(
        tripId!,
        signal ?? new AbortController().signal,
      );
      let runtimeLease: ReturnType<typeof beginPhotoDownloadNamespaceOperation> | null = null;
      let localLease: LocalPhotoLease | null = null;
      let boundaryReleased = false;
      const releaseBoundary = (): void => {
        if (boundaryReleased) return;
        boundaryReleased = true;
        runtimeLease?.finish();
        contextLease.release();
      };
      try {
        contextLease.assertActive();
        runtimeLease = beginPhotoDownloadNamespaceOperation(
          contextLease.context,
          contextLease.context.signal,
        );
        const fencedSignal = AbortSignal.any([
          contextLease.context.signal,
          runtimeLease.signal,
        ]);
        localLease = await openLocalPhoto(
          { ...contextLease.context, signal: fencedSignal },
          assetId,
          quality,
          fencedSignal,
        );
        contextLease.assertActive();
        if (!localLease) {
          releaseBoundary();
          return null;
        }
        let released = false;
        const retainedLocalLease = localLease;
        const release = (): void => {
          if (released) return;
          released = true;
          fencedSignal.removeEventListener('abort', release);
          try {
            retainedLocalLease.release();
          } finally {
            releaseBoundary();
          }
        };
        fencedSignal.addEventListener('abort', release, { once: true });
        if (fencedSignal.aborted) {
          release();
          throw fencedSignal.reason instanceof Error
            ? fencedSignal.reason
            : new Error('The private photo view was cancelled.');
        }
        return { ...retainedLocalLease, release };
      } catch (error) {
        try {
          localLease?.release();
        } finally {
          releaseBoundary();
        }
        throw error;
      }
    };
    return operation().catch(async (error: unknown) => {
      await invalidate();
      throw error;
    });
  }, [invalidate, tripId]);
  const planSelected = useCallback((
    assets: readonly MyPhotosAsset[],
    galleryRevision: number,
  ) => planAsync({ kind: 'selected', assets, galleryRevision }), [planAsync]);
  const planAllMatched = useCallback(
    (summary: MyPhotosSummary) => planAsync({ kind: 'all_matched', summary }),
    [planAsync],
  );
  const planFilterSelection = useCallback((
    summary: MyPhotosSummary,
    filter: 'best' | 'possible',
    excludedAssetIds: readonly string[],
  ) => planAsync({ kind: 'filter_selection', summary, filter, excludedAssetIds }), [planAsync]);
  const activatePlan = useCallback((
    value: PhotoDownloadPlan,
    quality: DownloadQuality,
    wifiOnly: boolean,
  ) => activateAsync({ plan: value, quality, wifiOnly }), [activateAsync]);
  const pause = useCallback(
    (jobId: string) => controlAsync({ action: 'pause', jobId }),
    [controlAsync],
  );
  const resume = useCallback(
    (jobId: string) => controlAsync({ action: 'resume', jobId }),
    [controlAsync],
  );
  const cancel = useCallback(
    (jobId: string) => controlAsync({ action: 'cancel', jobId }),
    [controlAsync],
  );
  const remove = useCallback(
    (jobId: string) => controlAsync({ action: 'remove', jobId }),
    [controlAsync],
  );
  const removeAllCompleted = useCallback(
    () => removeAllAsync(),
    [removeAllAsync],
  );
  const clearAllStorage = useCallback(
    () => clearStorageAsync(),
    [clearStorageAsync],
  );

  return {
    jobs,
    storage,
    plan,
    activate,
    control,
    reconcile,
    removeAll,
    clearStorage,
    openLocal,
    refresh: invalidate,
    planSelected,
    planAllMatched,
    planFilterSelection,
    activatePlan,
    pause,
    resume,
    cancel,
    remove,
    removeAllCompleted,
    clearAllStorage,
  } as const;
}

/** One owner-scoped local keyset page. `gcTime: 0` ensures traversing a
 * 5,000-item manifest never accumulates every visited page in React Query. */
export function useCompletedPhotoDownloadsPage(
  tripId: string | null,
  cursor: CompletedPhotoDownloadCursor | null,
) {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const boundary = principal?.principalType === 'passenger' && principal.passengerId
    ? {
        namespace: principalAccountNamespace(principal),
        passengerId: principal.passengerId,
      }
    : null;
  const cursorKey = cursor
    ? `${cursor.direction}:${cursor.completedAt}:${cursor.id}`
    : 'first';
  return useQuery({
    queryKey: [
      'my-photos-completed-downloads', boundary?.namespace,
      boundary?.passengerId, tripId, cursorKey,
    ],
    queryFn: ({ signal }) => withFencedPhotoDownloadContext(
      tripId!,
      signal,
      (context) => listCompletedPhotoDownloadsPage(context, cursor, 24),
    ),
    enabled: Boolean(boundary && tripId),
    staleTime: 1_000,
    gcTime: 0,
  });
}

/** Loads exactly one manifest row through the active account/trip/passenger
 * boundary; a route job id remains a locator and never grants access. */
export function useOwnedPhotoDownload(tripId: string | null, jobId: string | null) {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const boundary = principal?.principalType === 'passenger' && principal.passengerId
    ? {
        namespace: principalAccountNamespace(principal),
        passengerId: principal.passengerId,
      }
    : null;
  return useQuery({
    queryKey: [
      'my-photos-download', boundary?.namespace,
      boundary?.passengerId, tripId, jobId,
    ],
    queryFn: ({ signal }) => withFencedPhotoDownloadContext(
      tripId!,
      signal,
      (context) => getPhotoDownload(context, jobId!),
    ),
    enabled: Boolean(boundary && tripId && jobId),
    staleTime: 1_000,
  });
}
