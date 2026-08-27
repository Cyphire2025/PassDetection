import { router, type Href } from 'expo-router';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import { useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { useMessages } from '@/core/localization/localization-provider';
import { ContentLoading } from '@/design/components/content-state';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

import type {
  CompletedPhotoDownloadCursor,
  PhotoDownloadJob,
} from '../downloads/download-repository';
import {
  useCompletedPhotoDownloadsPage,
  usePhotoDownloads,
} from '../hooks/use-photo-downloads';
import { useMyPhotosMutations, useMyPhotosSummary } from '../hooks/use-my-photos';
import { DownloadedPhotosCard } from './downloaded-photos-card';
import { formatPrivatePhotoBytes } from './format-private-bytes';
import { MyPhotosManagementCard } from './my-photos-management-card';
import {
  myPhotosRequestErrorPresentation,
  myPhotosUnavailablePresentation,
} from './my-photos-request-state';
import { MyPhotosStatusPanel } from './my-photos-status-panel';
import { PhotoDownloadQueueCard } from './photo-download-queue-card';

export function MyPhotosStorageScreen() {
  const messages = useMessages();
  const trips = useTrips();
  const tripId = trips.selectedTripId;
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  const ownerIdentity = useMemo(() => (
    principal?.principalType === 'passenger' && tripId
      ? `${principalAccountNamespace(principal)}:${principal.passengerId}:${tripId}`
      : 'none'
  ), [principal, tripId]);
  const [completedPosition, setCompletedPosition] = useState<Readonly<{
    ownerIdentity: string;
    cursor: CompletedPhotoDownloadCursor | null;
  }>>({ ownerIdentity, cursor: null });
  const [removing, setRemoving] = useState<Readonly<{
    ownerIdentity: string;
    jobId: string;
  }> | null>(null);
  const completedCursor = completedPosition.ownerIdentity === ownerIdentity
    ? completedPosition.cursor
    : null;
  const removingJobId = removing?.ownerIdentity === ownerIdentity ? removing.jobId : null;
  const setOwnerCompletedCursor = useCallback((cursor: CompletedPhotoDownloadCursor) => {
    setCompletedPosition({ ownerIdentity, cursor });
  }, [ownerIdentity]);
  const summary = useMyPhotosSummary(tripId);
  const mutations = useMyPhotosMutations(tripId);
  const downloads = usePhotoDownloads(tripId);
  const completedDownloads = useCompletedPhotoDownloadsPage(tripId, completedCursor);
  const {
    cancel: cancelDownload,
    clearAllStorage,
    pause: pauseDownload,
    removeAllCompleted,
    remove: removeDownload,
    resume: resumeDownload,
  } = downloads;
  const removeDownloads = useCallback(async () => {
    try {
      await removeAllCompleted();
      Alert.alert(messages.myPhotosDownloadsRemoved());
    } catch {
      Alert.alert(messages.myPhotosDownloadFailed());
    }
  }, [messages, removeAllCompleted]);
  const clearStorage = useCallback(async () => {
    try {
      await clearAllStorage();
      Alert.alert(messages.myPhotosStorageCleared());
    } catch {
      Alert.alert(messages.myPhotosDownloadFailed());
    }
  }, [clearAllStorage, messages]);
  const openDownloadedPhoto = useCallback((job: PhotoDownloadJob) => {
    router.push(`/(passenger)/my-photos/downloaded/${encodeURIComponent(job.id)}` as Href);
  }, []);
  const removeDownloadedPhoto = useCallback((job: PhotoDownloadJob) => {
    Alert.alert(
      messages.myPhotosRemoveDownloadedPhoto(),
      messages.myPhotosRemoveDownloadedPhotoWarning(),
      [
        { text: messages.myPhotosCancel(), style: 'cancel' },
        {
          text: messages.myPhotosConfirmRemove(),
          style: 'destructive',
          onPress: () => {
            setRemoving({ ownerIdentity, jobId: job.id });
            void removeDownload(job.id)
              .catch(() => Alert.alert(messages.myPhotosDownloadFailed()))
              .finally(() => setRemoving((current) => (
                current?.ownerIdentity === ownerIdentity && current.jobId === job.id
                  ? null
                  : current
              )));
          },
        },
      ],
    );
  }, [messages, ownerIdentity, removeDownload]);
  const controlDownload = useCallback(async (
    action: 'pause' | 'resume' | 'cancel',
    jobId: string,
  ) => {
    try {
      if (action === 'pause') await pauseDownload(jobId);
      else if (action === 'resume') await resumeDownload(jobId);
      else await cancelDownload(jobId);
    } catch {
      Alert.alert(messages.myPhotosDownloadFailed());
    }
  }, [cancelDownload, messages, pauseDownload, resumeDownload]);
  const deleteEnrollment = useCallback(async (
    scope: 'enrollment_only' | 'enrollment_and_search_data',
  ) => {
    if (!tripId || summary.isError || !summary.data) return;
    try {
      const result = await mutations.deleteEnrollment.mutateAsync(scope);
      await summary.refetch();
      if (result.provider_deletion_status === 'pending') {
        Alert.alert(messages.myPhotosProviderDeletionPending());
      } else if (result.provider_deletion_status === 'failed') {
        Alert.alert(
          messages.myPhotosProviderDeletionFailed(),
          result.provider_deletion_retryable
            ? messages.myPhotosProviderDeletionRetryable()
            : undefined,
        );
      }
    } catch (error) {
      const presentation = myPhotosRequestErrorPresentation(error, messages);
      Alert.alert(presentation.title, presentation.message);
    }
  }, [messages, mutations.deleteEnrollment, summary, tripId]);

  const header = (
    <View style={styles.header}>
      <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosClose()} onPress={() => router.back()} style={styles.back}>
        <ChevronLeft color={colors.ink} size={27} />
      </Pressable>
      <Text accessibilityRole="header" style={styles.headerTitle}>{messages.myPhotosStorageAndPrivacy()}</Text>
    </View>
  );
  if (!tripId) {
    return (
      <Screen contentStyle={styles.screen}>
        {header}
        <MyPhotosStatusPanel
          onOpenFaceScan={() => undefined}
          onRefresh={() => undefined}
          presentation={myPhotosUnavailablePresentation(messages)}
        />
      </Screen>
    );
  }
  const serverActionsAvailable = !summary.isPending && !summary.isError && Boolean(summary.data);
  const requestErrorPresentation = summary.isError || (!summary.isPending && !summary.data)
    ? myPhotosRequestErrorPresentation(summary.error, messages)
    : null;
  return (
    <Screen contentStyle={styles.screen}>
      {header}
      <PageHeader
        eyebrow={summary.data?.value.group_name ?? trips.selectedTrip?.name ?? messages.myPhotos()}
        title={messages.myPhotosStorageAndPrivacy()}
        subtitle={messages.myPhotosStorageExplanation()}
        tone="passenger"
      />
      {summary.isPending ? (
        <ContentLoading label={messages.loading()} />
      ) : requestErrorPresentation ? (
        <MyPhotosStatusPanel
          onOpenFaceScan={() => undefined}
          onRefresh={() => void summary.refetch()}
          presentation={requestErrorPresentation}
        />
      ) : null}
      <View style={styles.storageSummary}>
        <Text style={styles.storageSummaryText}>{messages.myPhotosDownloadQueueSummary(
          downloads.storage.data?.completedCount ?? 0,
          downloads.storage.data?.activeCount ?? 0,
        )}</Text>
        <Text style={styles.storageSummaryText}>{messages.myPhotosStorageUsed(formatPrivatePhotoBytes(
          downloads.storage.data?.encryptedBytes ?? 0,
        ))}</Text>
      </View>
      <PhotoDownloadQueueCard
        activeCount={downloads.storage.data?.activeCount ?? 0}
        completedCount={downloads.storage.data?.completedCount ?? 0}
        jobs={downloads.jobs.data ?? []}
        onCancel={(jobId) => void controlDownload('cancel', jobId)}
        onPause={(jobId) => void controlDownload('pause', jobId)}
        onResume={(jobId) => void controlDownload('resume', jobId)}
      />
      <DownloadedPhotosCard
        error={completedDownloads.isError}
        loading={completedDownloads.isPending || completedDownloads.isFetching}
        onNext={() => {
          const cursor = completedDownloads.data?.nextCursor;
          if (cursor) setOwnerCompletedCursor(cursor);
        }}
        onOpen={openDownloadedPhoto}
        onPrevious={() => {
          const cursor = completedDownloads.data?.previousCursor;
          if (cursor) setOwnerCompletedCursor(cursor);
        }}
        onRemove={removeDownloadedPhoto}
        onRetry={() => void completedDownloads.refetch()}
        page={completedDownloads.data ?? null}
        removingJobId={removingJobId}
        {...(trips.selectedTrip?.timeZone ? { timeZone: trips.selectedTrip.timeZone } : {})}
      />
      <MyPhotosManagementCard
        busy={mutations.deleteEnrollment.isPending || downloads.control.isPending || downloads.removeAll.isPending || downloads.clearStorage.isPending}
        onClearStorage={() => void clearStorage()}
        onDeleteEnrollment={(scope) => void deleteEnrollment(scope)}
        onRemoveDownloads={() => void removeDownloads()}
        serverActionsAvailable={serverActionsAvailable}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  header: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  back: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { flex: 1, color: colors.ink, fontSize: 20, fontWeight: '900' },
  storageSummary: { gap: spacing.xs },
  storageSummaryText: { color: colors.inkMuted, fontSize: 13, lineHeight: 20 },
});
