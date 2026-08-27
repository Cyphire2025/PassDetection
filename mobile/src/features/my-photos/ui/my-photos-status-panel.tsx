import CircleCheckBig from 'lucide-react-native/icons/circle-check-big';
import Clock3 from 'lucide-react-native/icons/clock-3';
import Images from 'lucide-react-native/icons/images';
import ShieldAlert from 'lucide-react-native/icons/shield-alert';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

import type { MyPhotosStatePresentation } from './summary-state';

type Props = Readonly<{
  presentation: MyPhotosStatePresentation;
  onRefresh: () => void;
  onOpenFaceScan: () => void;
}>;

export function MyPhotosStatusPanel({ presentation, onRefresh, onOpenFaceScan }: Props) {
  const messages = useMessages();
  const icon = presentation.busy
    ? <ActivityIndicator accessibilityLabel={messages.loading()} color={colors.greenDeep} size="small" />
    : presentation.tone === 'danger' || presentation.tone === 'warning'
      ? <ShieldAlert color={presentation.tone === 'danger' ? colors.danger : colors.warning} size={26} />
      : presentation.tone === 'success'
        ? <CircleCheckBig color={colors.greenDeep} size={26} />
        : presentation.tone === 'progress'
          ? <Clock3 color={colors.greenDeep} size={26} />
          : <Images color={colors.greenDeep} size={26} />;
  return (
    <GlassCard
      accessibilityLiveRegion={presentation.busy ? 'polite' : 'none'}
      style={[
        styles.card,
        presentation.tone === 'danger' && styles.danger,
        presentation.tone === 'warning' && styles.warning,
      ]}>
      <View style={styles.headingRow}>
        <View style={styles.icon}>{icon}</View>
        <Text accessibilityRole="header" style={styles.title}>{presentation.title}</Text>
      </View>
      <Text style={styles.message}>{presentation.message}</Text>
      {presentation.action === 'refresh' ? (
        <PrimaryButton label={messages.tryAgain()} tone="secondary" onPress={onRefresh} />
      ) : presentation.action === 'open_face_scan' ? (
        <PrimaryButton label={messages.myPhotosSetUpFaceScan()} onPress={onOpenFaceScan} />
      ) : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  danger: { borderColor: 'rgba(184,64,77,0.32)', backgroundColor: 'rgba(255,242,243,0.94)' },
  warning: { borderColor: 'rgba(207,126,43,0.34)', backgroundColor: 'rgba(255,248,237,0.94)' },
  headingRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  icon: { width: 42, height: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 14, backgroundColor: colors.greenSoft },
  title: { flex: 1, color: colors.ink, fontSize: 18, fontWeight: '900', lineHeight: 23 },
  message: { color: colors.inkMuted, fontSize: 14, lineHeight: 21 },
});
