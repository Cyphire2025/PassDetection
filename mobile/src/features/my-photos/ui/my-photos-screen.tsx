import { router } from 'expo-router';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import Settings from 'lucide-react-native/icons/settings';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { ContentLoading } from '@/design/components/content-state';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { SensitiveScreenProtection } from '@/core/security/sensitive-screen-protection';
import { colors, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

import type { MatchFilter, MyPhotosAsset } from '../api/contracts';
import type { PhotoDownloadPlan } from '../downloads/download-manager';
import { photoDownloadPlanView, usePhotoDownloads } from '../hooks/use-photo-downloads';
import { useMyPhotosSummary } from '../hooks/use-my-photos';
import {
  createMyPhotosImageCacheScope,
  createMyPhotosRemoteImageResolver,
} from '../media/photo-image-source';
import type { GallerySelection } from './gallery-selection';
import { shouldShowMyPhotosGallery } from './gallery-visibility';
import { formatPrivatePhotoBytes } from './format-private-bytes';
import { MyPhotosGallery } from './my-photos-gallery';
import { MyPhotosOverview } from './my-photos-overview';
import {
  myPhotosAccessRevokedPresentation,
  myPhotosRequestErrorPresentation,
  myPhotosUnavailablePresentation,
} from './my-photos-request-state';
import { MyPhotosStatusPanel } from './my-photos-status-panel';
import { PhotoDownloadPlanModal } from './photo-download-plan-modal';
import { PhotoDownloadQueueCard } from './photo-download-queue-card';
import { photoDownloadStatusCopy } from './photo-download-status-copy';
import { photoTileDownloadStates } from './photo-tile-download-state';
import { myPhotosStatePresentation } from './summary-state';

export function MyPhotosScreen() {
  const messages = useMessages();
  const trips = useTrips();
  const session = useSessionStore((state) => state.session);
  const tripId = trips.selectedTripId;
  const summary = useMyPhotosSummary(tripId);
  const downloads = usePhotoDownloads(tripId);
  const {
    activatePlan,
    cancel: cancelDownload,
    pause: pauseDownload,
    planAllMatched,
    planFilterSelection,
    planSelected,
    resume: resumeDownload,
  } = downloads;
  const [downloadPlan, setDownloadPlan] = useState<PhotoDownloadPlan | null>(null);
  const recordedSearchId = useRef<string | null>(null);
  const value = summary.data?.value;
  const cacheBoundary = value
    ? `${tripId}:${value.gallery.published_revision}:${value.results.snapshot_revision}`
    : 'none';
  const [galleryCacheState, setGalleryCacheState] = useState<Readonly<{
    boundary: string;
    source: 'network' | 'offline';
    partial: boolean;
  }> | null>(null);
  const effectiveCacheState = useMemo(() => (
    summary.data
      ? galleryCacheState?.boundary === cacheBoundary
        ? {
            source: summary.data.source === 'offline' || galleryCacheState.source === 'offline'
              ? 'offline' as const
              : 'network' as const,
            partial: summary.data.partial || galleryCacheState.partial,
          }
        : { source: summary.data.source, partial: summary.data.partial }
      : null
  ), [cacheBoundary, galleryCacheState, summary.data]);
  const presentation = useMemo(
    () => value && effectiveCacheState
      ? myPhotosStatePresentation(value, messages, effectiveCacheState)
      : null,
    [effectiveCacheState, messages, value],
  );
  const updateGalleryCacheState = useCallback((state: Readonly<{
    source: 'network' | 'offline';
    partial: boolean;
  }>) => {
    setGalleryCacheState({ boundary: cacheBoundary, ...state });
  }, [cacheBoundary]);
  const search = summary.data?.value.search;
  useEffect(() => {
    if (
      !search?.id
      || !search.started_at
      || !search.completed_at
      || search.status !== 'complete'
      || recordedSearchId.current === search.id
    ) return;
    const duration = Date.parse(search.completed_at) - Date.parse(search.started_at);
    if (Number.isFinite(duration) && duration >= 0) {
      recordedSearchId.current = search.id;
      recordMobileMetric('my_photos_search_duration', duration, { outcome: 'success' });
    }
  }, [search?.completed_at, search?.id, search?.started_at, search?.status]);
  const openFaceScan = useCallback(() => router.push('/(passenger)/my-photos/face-scan'), []);
  const openStorage = useCallback(() => router.push('/(passenger)/my-photos/storage'), []);
  const showDownloadError = useCallback((error: unknown) => {
    const failure = myPhotosRequestErrorPresentation(error, messages);
    Alert.alert(messages.myPhotosDownloadFailed(), `${failure.title} ${failure.message}`);
  }, [messages]);
  const download = useCallback(async (
    selection: GallerySelection,
    assets: readonly MyPhotosAsset[],
    filter: MatchFilter,
  ) => {
    if (downloads.plan.isPending || !value) return;
    try {
      const snapshotRevision = filter === 'all'
        ? value.gallery.published_revision
        : value.results.snapshot_revision;
      if (selection.mode === 'explicit') {
        if (assets.length === 0) return;
        setDownloadPlan(await planSelected(assets, snapshotRevision));
      } else {
        if (filter === 'all') return;
        setDownloadPlan(await planFilterSelection(
          value,
          filter,
          [...selection.excludedAssetIds],
        ));
      }
    } catch (error) {
      showDownloadError(error);
    }
  }, [downloads.plan.isPending, planFilterSelection, planSelected, showDownloadError, value]);
  const downloadAllMatched = useCallback(async () => {
    if (!value || downloads.plan.isPending) return;
    try {
      setDownloadPlan(await planAllMatched(value));
    } catch (error) {
      showDownloadError(error);
    }
  }, [downloads.plan.isPending, planAllMatched, showDownloadError, value]);
  const activateDownloadPlan = useCallback(async (
    quality: 'original' | 'optimized',
    wifiOnly: boolean,
  ) => {
    if (!downloadPlan) return;
    try {
      await activatePlan(downloadPlan, quality, wifiOnly);
      setDownloadPlan(null);
    } catch (error) {
      showDownloadError(error);
    }
  }, [activatePlan, downloadPlan, showDownloadError]);
  const controlDownload = useCallback(async (
    action: 'pause' | 'resume' | 'cancel',
    jobId: string,
  ) => {
    try {
      if (action === 'pause') await pauseDownload(jobId);
      else if (action === 'resume') await resumeDownload(jobId);
      else await cancelDownload(jobId);
    } catch (error) {
      showDownloadError(error);
    }
  }, [cancelDownload, pauseDownload, resumeDownload, showDownloadError]);
  const imageNamespace = session?.principal.principalType === 'passenger'
    ? principalAccountNamespace(session.principal)
    : null;
  const imagePassengerId = session?.principal.principalType === 'passenger'
    ? session.principal.passengerId
    : null;
  const imageAccessToken = session?.accessToken ?? null;
  const tileDownloadStates = useMemo(
    () => photoTileDownloadStates(
      downloads.jobs.data ?? [],
      (state, progress) => photoDownloadStatusCopy(state, messages, progress),
    ),
    [downloads.jobs.data, messages],
  );
  const imageCacheScope = useMemo(
    () => imageNamespace && imagePassengerId
      ? createMyPhotosImageCacheScope(imageNamespace, imagePassengerId)
      : null,
    [imageNamespace, imagePassengerId],
  );
  const imageResolver = useMemo(
    () => tripId && imageAccessToken && imageCacheScope
      ? createMyPhotosRemoteImageResolver(tripId, imageCacheScope)
      : null,
    [imageAccessToken, imageCacheScope, tripId],
  );
  useEffect(() => () => {
    void imageResolver?.clear();
  }, [imageResolver]);
  const resolveThumbnail = useCallback((asset: MyPhotosAsset, signal?: AbortSignal) => (
    imageResolver?.resolve(asset, 'thumbnail', signal) ?? Promise.resolve(null)
  ), [imageResolver]);
  const header = (
    <View style={styles.header}>
      <View style={styles.headerActions}>
        <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosClose()} onPress={() => router.back()} style={styles.iconButton}>
          <ChevronLeft color={colors.ink} size={27} />
        </Pressable>
        {tripId ? (
          <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosStorageAndPrivacy()} onPress={openStorage} style={styles.iconButton}>
            <Settings color={colors.ink} size={23} />
          </Pressable>
        ) : null}
      </View>
      <PageHeader
        eyebrow={value?.group_name ?? trips.selectedTrip?.name ?? messages.myPhotos()}
        title={messages.myPhotos()}
        subtitle={messages.myPhotosTripShortcut()}
        tone="passenger"
      />
    </View>
  );

  if (!tripId) {
    return (
      <Screen contentStyle={styles.scrollScreen}>
        {header}
        <MyPhotosStatusPanel
          onOpenFaceScan={openFaceScan}
          onRefresh={() => undefined}
          presentation={myPhotosUnavailablePresentation(messages)}
        />
      </Screen>
    );
  }
  if (summary.isPending) {
    return (
      <Screen contentStyle={styles.scrollScreen}>
        {header}
        <ContentLoading label={messages.loading()} />
      </Screen>
    );
  }
  if (summary.isError || !summary.data || !value || !presentation) {
    return (
      <Screen contentStyle={styles.scrollScreen}>
        {header}
        <MyPhotosStatusPanel
          onOpenFaceScan={openFaceScan}
          onRefresh={() => void summary.refetch()}
          presentation={myPhotosRequestErrorPresentation(summary.error, messages)}
        />
      </Screen>
    );
  }
  if (!imageNamespace) {
    return (
      <Screen contentStyle={styles.scrollScreen}>
        {header}
        <MyPhotosStatusPanel
          onOpenFaceScan={openFaceScan}
          onRefresh={() => undefined}
          presentation={myPhotosAccessRevokedPresentation(messages)}
        />
      </Screen>
    );
  }
  const showGallery = shouldShowMyPhotosGallery(value);
  if (!showGallery) {
    return (
      <Screen contentStyle={styles.scrollScreen}>
        {header}
        <MyPhotosStatusPanel
          onOpenFaceScan={openFaceScan}
          onRefresh={() => void summary.refetch()}
          presentation={presentation}
        />
      </Screen>
    );
  }
  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.fillScreen}>
      <ScrollView contentContainerStyle={styles.summary} bounces={false}>
        {header}
        <MyPhotosOverview
          downloadedCount={downloads.storage.data?.completedCount ?? 0}
          storageUsedLabel={formatPrivatePhotoBytes(downloads.storage.data?.encryptedBytes ?? 0)}
          summary={value}
          {...(trips.selectedTrip?.timeZone ? { timeZone: trips.selectedTrip.timeZone } : {})}
        />
        <PhotoDownloadQueueCard
          activeCount={downloads.storage.data?.activeCount ?? 0}
          completedCount={downloads.storage.data?.completedCount ?? 0}
          jobs={downloads.jobs.data ?? []}
          onCancel={(jobId) => void controlDownload('cancel', jobId)}
          onPause={(jobId) => void controlDownload('pause', jobId)}
          onResume={(jobId) => void controlDownload('resume', jobId)}
        />
        {value.experience_state === 'matches_preparing'
        || value.experience_state === 'search_queued'
        || value.experience_state === 'searching'
        || value.experience_state === 'enrollment_deleted'
        || value.experience_state === 'no_matches'
        || effectiveCacheState?.source === 'offline' ? (
          <MyPhotosStatusPanel
            onOpenFaceScan={openFaceScan}
            onRefresh={() => void summary.refetch()}
            presentation={presentation}
          />
        ) : null}
      </ScrollView>
      <MyPhotosGallery
        accountBoundary={imageNamespace}
        downloadStates={tileDownloadStates}
        onDownload={download}
        onDownloadAllMatches={() => void downloadAllMatched()}
        onCacheStateChange={updateGalleryCacheState}
        resolveThumbnail={resolveThumbnail}
        summary={summary.data}
        tripId={tripId}
      />
      <PhotoDownloadPlanModal
        busy={downloads.activate.isPending}
        onCancel={() => setDownloadPlan(null)}
        onConfirm={(quality, wifiOnly) => void activateDownloadPlan(quality, wifiOnly)}
        plan={downloadPlan ? photoDownloadPlanView(downloadPlan) : null}
      />
      <SensitiveScreenProtection protectionKey="my-photos-gallery" />
    </Screen>
  );
}

const styles = StyleSheet.create({
  scrollScreen: { gap: spacing.lg },
  fillScreen: { paddingHorizontal: 0 },
  header: { gap: spacing.sm },
  headerActions: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  iconButton: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  summary: { gap: spacing.md, paddingHorizontal: spacing.lg, paddingBottom: spacing.md },
});
