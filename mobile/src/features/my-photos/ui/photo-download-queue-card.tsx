import { useCallback } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';

import type { PhotoDownloadJob } from '../downloads/download-repository';
import { photoDownloadStatusCopy } from './photo-download-status-copy';

const VISIBLE_JOB_LIMIT = 6;

type Props = Readonly<{
  jobs: readonly PhotoDownloadJob[];
  completedCount: number;
  activeCount: number;
  onPause: (jobId: string) => void;
  onResume: (jobId: string) => void;
  onCancel: (jobId: string) => void;
}>;

function isActive(job: PhotoDownloadJob): boolean {
  return !['completed', 'cancelled', 'failed', 'corrupt', 'removed'].includes(job.state);
}

function progressPercent(job: PhotoDownloadJob): number {
  if (!job.expectedSizeBytes || job.expectedSizeBytes <= 0) return 0;
  return Math.min(100, Math.max(0, job.verifiedPlaintextBytes / job.expectedSizeBytes * 100));
}

function visibleJobs(jobs: readonly PhotoDownloadJob[]): Readonly<{
  values: readonly PhotoDownloadJob[];
  hiddenCount: number;
}> {
  const active: PhotoDownloadJob[] = [];
  const terminal: PhotoDownloadJob[] = [];
  for (const job of jobs) {
    if (job.state === 'removed') continue;
    (isActive(job) ? active : terminal).push(job);
  }
  const total = active.length + terminal.length;
  return {
    values: [...active, ...terminal].slice(0, VISIBLE_JOB_LIMIT),
    hiddenCount: Math.max(0, total - VISIBLE_JOB_LIMIT),
  };
}

export function PhotoDownloadQueueCard({
  jobs,
  completedCount,
  activeCount,
  onPause,
  onResume,
  onCancel,
}: Props) {
  const messages = useMessages();
  const visible = visibleJobs(jobs);
  const action = useCallback((job: PhotoDownloadJob) => {
    if (job.state === 'paused' || job.state === 'failed' || job.state === 'corrupt' || job.state === 'cancelled') {
      onResume(job.id);
    } else if (isActive(job)) {
      onPause(job.id);
    }
  }, [onPause, onResume]);
  if (visible.values.length === 0 && completedCount === 0 && activeCount === 0) return null;

  return (
    <GlassCard style={styles.card}>
      <View style={styles.header}>
        <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosDownloadQueue()}</Text>
        <Text accessibilityLiveRegion="polite" style={styles.summary}>
          {messages.myPhotosDownloadQueueSummary(completedCount, activeCount)}
        </Text>
      </View>
      {visible.values.map((job, index) => {
        const canToggle = isActive(job) || ['failed', 'corrupt', 'cancelled'].includes(job.state);
        const resumable = ['paused', 'failed', 'corrupt', 'cancelled'].includes(job.state);
        return (
          <View key={job.id} style={styles.job}>
            <View style={styles.jobCopy}>
              <Text style={styles.jobTitle}>{messages.myPhotosDownloadItem(index + 1)}</Text>
              <Text accessibilityLiveRegion="polite" style={styles.jobStatus}>
                {photoDownloadStatusCopy(job.state, messages, progressPercent(job))}
              </Text>
            </View>
            {canToggle ? (
              <Pressable accessibilityRole="button" onPress={() => action(job)} style={styles.jobAction}>
                <Text style={styles.jobActionText}>
                  {resumable ? messages.myPhotosResumeDownloads() : messages.myPhotosPauseDownloads()}
                </Text>
              </Pressable>
            ) : null}
            {isActive(job) ? (
              <Pressable accessibilityRole="button" onPress={() => onCancel(job.id)} style={styles.jobAction}>
                <Text style={styles.cancelText}>{messages.myPhotosCancelDownload()}</Text>
              </Pressable>
            ) : null}
          </View>
        );
      })}
      {visible.hiddenCount > 0 ? (
        <Text style={styles.more}>{messages.myPhotosMoreDownloads(visible.hiddenCount)}</Text>
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  header: { gap: spacing.xs },
  title: { color: colors.ink, fontSize: 18, fontWeight: '900' },
  summary: { color: colors.inkMuted, fontSize: 13 },
  job: { minHeight: 54, flexDirection: 'row', alignItems: 'center', gap: spacing.sm, borderRadius: radii.sm, backgroundColor: colors.aquaSoft, padding: spacing.sm },
  jobCopy: { flex: 1, gap: 2 },
  jobTitle: { color: colors.ink, fontSize: 13, fontWeight: '800' },
  jobStatus: { color: colors.inkMuted, fontSize: 11 },
  jobAction: { minHeight: 44, justifyContent: 'center', paddingHorizontal: spacing.xs },
  jobActionText: { color: colors.greenDeep, fontSize: 11, fontWeight: '900' },
  cancelText: { color: colors.danger, fontSize: 11, fontWeight: '900' },
  more: { color: colors.inkMuted, fontSize: 12, textAlign: 'center' },
});
