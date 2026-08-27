import { useState } from 'react';
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, radii, spacing } from '@/design/theme';

import type { DownloadQuality } from '../api/contracts';
import { formatPrivatePhotoBytes } from './format-private-bytes';

export type PhotoDownloadPlanPresentation = Readonly<{
  id: string;
  itemCount: number;
  qualities: readonly DownloadQuality[];
  estimatedBytes: Readonly<Partial<Record<DownloadQuality, number>>>;
  canStart: Readonly<Partial<Record<DownloadQuality, boolean>>>;
  availableDeviceBytes: number;
  substantial: Readonly<Partial<Record<DownloadQuality, boolean>>>;
}>;

type Props = Readonly<{
  plan: PhotoDownloadPlanPresentation | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (quality: DownloadQuality, wifiOnly: boolean) => void;
}>;

export function PhotoDownloadPlanModal({ plan, busy, onCancel, onConfirm }: Props) {
  const messages = useMessages();
  const [choice, setChoice] = useState<Readonly<{
    planId: string | null;
    quality: DownloadQuality;
    wifiOnly: boolean;
  }>>({ planId: null, quality: 'optimized', wifiOnly: true });
  const defaultQuality = plan?.qualities.includes('optimized') ? 'optimized' : 'original';
  const quality = plan && choice.planId === plan.id && plan.qualities.includes(choice.quality)
    ? choice.quality
    : defaultQuality;
  const wifiOnly = plan && choice.planId === plan.id ? choice.wifiOnly : true;
  const estimate = plan?.estimatedBytes[quality] ?? 0;
  const canStart = plan?.canStart[quality] === true;

  const chooseQuality = (next: DownloadQuality) => {
    if (!plan) return;
    setChoice((current) => ({
      planId: plan.id,
      quality: next,
      wifiOnly: current.planId === plan.id ? current.wifiOnly : true,
    }));
  };
  const chooseWifiOnly = (next: boolean) => {
    if (!plan) return;
    setChoice((current) => ({ planId: plan.id, quality, wifiOnly: next }));
  };

  return (
    <Modal
      animationType="fade"
      onRequestClose={onCancel}
      presentationStyle="overFullScreen"
      transparent
      visible={Boolean(plan)}>
      <View accessibilityViewIsModal style={styles.backdrop}>
        <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosCancel()} onPress={onCancel} style={StyleSheet.absoluteFill} />
        {plan ? (
          <View style={styles.sheet}>
            <ScrollView contentContainerStyle={styles.content}>
              <Text accessibilityRole="header" style={styles.title}>{messages.myPhotosChooseDownloadQuality()}</Text>
              <Text style={styles.body}>{messages.myPhotosPhotosFound(plan.itemCount)}</Text>
              <View accessibilityRole="radiogroup" style={styles.qualityGroup}>
                {plan.qualities.map((item) => {
                  const selected = item === quality;
                  return (
                    <Pressable
                      accessibilityRole="radio"
                      accessibilityState={{ checked: selected }}
                      key={item}
                      onPress={() => chooseQuality(item)}
                      style={[styles.quality, selected && styles.qualitySelected]}>
                      <Text style={[styles.qualityText, selected && styles.qualityTextSelected]}>
                        {item === 'original'
                          ? messages.myPhotosOriginalQuality()
                          : messages.myPhotosOptimizedQuality()}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
              <View style={styles.estimate}>
                <Text style={styles.estimateText}>{messages.myPhotosDownloadSizeEstimate(formatPrivatePhotoBytes(estimate))}</Text>
                <Text style={styles.availableText}>{messages.myPhotosDeviceSpaceAvailable(formatPrivatePhotoBytes(plan.availableDeviceBytes))}</Text>
              </View>
              {plan.substantial[quality] ? (
                <Text accessibilityLiveRegion="polite" style={styles.warning}>{messages.myPhotosLargeDownloadWarning()}</Text>
              ) : null}
              {!canStart ? (
                <Text accessibilityLiveRegion="assertive" style={styles.error}>{messages.myPhotosNotEnoughSpace()}</Text>
              ) : null}
              <View style={styles.wifiRow}>
                <Text style={styles.wifiLabel}>{messages.myPhotosWifiOnly()}</Text>
                <Switch
                  accessibilityLabel={messages.myPhotosWifiOnly()}
                  onValueChange={chooseWifiOnly}
                  trackColor={{ false: colors.border, true: colors.greenSoft }}
                  thumbColor={wifiOnly ? colors.greenDeep : colors.inkMuted}
                  value={wifiOnly}
                />
              </View>
              <Text style={styles.note}>{messages.myPhotosDownloadForegroundNote()}</Text>
              <PrimaryButton
                disabled={!canStart}
                label={messages.myPhotosStartDownload()}
                loading={busy}
                onPress={() => onConfirm(quality, wifiOnly)}
              />
              <PrimaryButton label={messages.myPhotosCancel()} tone="secondary" onPress={onCancel} />
            </ScrollView>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(8,41,54,0.56)' },
  sheet: { maxHeight: '88%', borderTopLeftRadius: radii.lg, borderTopRightRadius: radii.lg, backgroundColor: colors.surfaceStrong },
  content: { gap: spacing.md, padding: spacing.xl, paddingBottom: spacing.xxl },
  title: { color: colors.ink, fontSize: 23, lineHeight: 29, fontWeight: '900' },
  body: { color: colors.inkMuted, fontSize: 14, lineHeight: 21 },
  qualityGroup: { gap: spacing.sm },
  quality: { minHeight: 50, justifyContent: 'center', borderRadius: radii.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.white, paddingHorizontal: spacing.md },
  qualitySelected: { borderColor: colors.greenDeep, backgroundColor: colors.greenSoft },
  qualityText: { color: colors.inkMuted, fontSize: 15, fontWeight: '800' },
  qualityTextSelected: { color: colors.greenDeep },
  estimate: { gap: spacing.xs },
  estimateText: { color: colors.ink, fontSize: 15, fontWeight: '900' },
  availableText: { color: colors.inkMuted, fontSize: 13 },
  warning: { color: colors.warning, fontSize: 13, lineHeight: 20, fontWeight: '800' },
  error: { color: colors.danger, fontSize: 13, lineHeight: 20, fontWeight: '900' },
  wifiRow: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  wifiLabel: { flex: 1, color: colors.ink, fontSize: 15, fontWeight: '800' },
  note: { color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
});
