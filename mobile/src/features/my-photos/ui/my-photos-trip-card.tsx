import { router } from 'expo-router';
import Images from 'lucide-react-native/icons/images';
import { useCallback } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { GlassCard } from '@/design/components/glass-card';
import { colors, radii, spacing } from '@/design/theme';

import { useMyPhotosSummary } from '../hooks/use-my-photos';
import { useMyPhotosCapabilityDecision } from '../hooks/my-photos-capability-policy';

export function MyPhotosTripCard({ tripId }: Readonly<{ tripId: string }>) {
  const messages = useMessages();
  const summary = useMyPhotosSummary(tripId);
  const capability = useMyPhotosCapabilityDecision(summary.data, summary.error);
  const state = summary.data?.value.experience_state;
  const subtitle = state === 'provider_not_configured'
    ? messages.myPhotosProviderUnavailable()
    : messages.myPhotosTripShortcut();
  const open = useCallback(() => {
    recordMobileMetric('my_photos_open', 1, { trigger: 'manual', outcome: 'success' });
    router.push('/(passenger)/my-photos');
  }, []);

  if (!capability.visible) return null;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${messages.myPhotosOpen()}. ${subtitle}`}
      onPress={open}
      style={({ pressed }) => pressed && styles.pressed}>
      <GlassCard style={styles.card}>
        <View style={styles.icon}>
          <Images color={colors.greenDeep} size={26} />
        </View>
        <View style={styles.copy}>
          <Text style={styles.eyebrow}>{messages.myPhotos()}</Text>
          <Text style={styles.title}>{messages.myPhotosOpen()}</Text>
          <Text style={styles.subtitle}>{subtitle}</Text>
        </View>
      </GlassCard>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.lg, borderRadius: radii.lg },
  icon: { width: 52, height: 52, borderRadius: 17, backgroundColor: colors.greenSoft, alignItems: 'center', justifyContent: 'center' },
  copy: { flex: 1, gap: 2 },
  eyebrow: { color: colors.greenDeep, fontSize: 11, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 0.8 },
  title: { color: colors.ink, fontSize: 19, fontWeight: '900' },
  subtitle: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  pressed: { opacity: 0.72 },
});
