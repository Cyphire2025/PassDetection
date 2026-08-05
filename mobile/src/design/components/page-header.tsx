import { LinearGradient } from 'expo-linear-gradient';
import BriefcaseBusiness from 'lucide-react-native/icons/briefcase-business';
import Plane from 'lucide-react-native/icons/plane';
import ShieldCheck from 'lucide-react-native/icons/shield-check';
import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { AmbientHeroGlow } from '@/design/components/ambient-hero-glow';
import { HeroParticles } from '@/design/components/hero-particles';
import { OfflineStatusChip } from '@/design/components/offline-status-chip';
import { colors, radii, spacing } from '@/design/theme';

export type PageHeaderTone = 'passenger' | 'manager' | 'coordinator' | 'neutral';

const toneConfig = {
  passenger: {
    colors: [colors.navy, '#15596A', colors.blueDeep] as const,
    accent: colors.aqua,
  },
  manager: {
    colors: [colors.navy, '#15596A', colors.blueDeep] as const,
    accent: colors.aqua,
  },
  coordinator: {
    colors: [colors.navy, '#15596A', colors.blueDeep] as const,
    accent: colors.aqua,
  },
  neutral: {
    colors: [colors.navy, colors.navySoft, colors.blueDeep] as const,
    accent: colors.aqua,
  },
} as const;

function EyebrowIcon({ tone }: { tone: PageHeaderTone }) {
  const Icon = tone === 'coordinator'
    ? ShieldCheck
    : tone === 'manager'
      ? BriefcaseBusiness
      : Plane;
  return <Icon color={colors.aqua} size={14} strokeWidth={2.2} />;
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  accessory,
  tone = 'neutral',
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  accessory?: ReactNode;
  tone?: PageHeaderTone;
}) {
  const config = toneConfig[tone];
  return (
    <LinearGradient
      colors={config.colors}
      end={{ x: 1, y: 1 }}
      start={{ x: 0, y: 0 }}
      style={styles.root}>
      <AmbientHeroGlow color={config.accent} style={styles.orb} />
      <HeroParticles />
      <View pointerEvents="none" style={styles.ring} />
      <View style={styles.topRow}>
        <View style={styles.eyebrowPill}>
          <EyebrowIcon tone={tone} />
          <Text style={styles.eyebrow}>{eyebrow || 'Group Companion'}</Text>
        </View>
        <View style={styles.accessory}>
          <OfflineStatusChip />
          {accessory}
        </View>
      </View>
      <View style={styles.text}>
        <Text accessibilityRole="header" style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      <View style={[styles.accentLine, { backgroundColor: config.accent }]} />
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  root: {
    minHeight: 164,
    overflow: 'hidden',
    borderRadius: radii.lg,
    padding: spacing.xl,
    gap: spacing.md,
    shadowColor: colors.navy,
    shadowOpacity: 0.22,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
    elevation: 7,
  },
  orb: {
    position: 'absolute',
    width: 144,
    height: 144,
    borderRadius: 72,
    right: -58,
    top: -66,
    opacity: 0.16,
  },
  ring: {
    position: 'absolute',
    width: 126,
    height: 126,
    borderRadius: 63,
    right: 20,
    bottom: -92,
    borderColor: 'rgba(255,255,255,0.16)',
    borderWidth: 22,
  },
  topRow: { minHeight: 30, flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between', gap: spacing.sm },
  eyebrowPill: {
    minHeight: 28,
    alignSelf: 'flex-start',
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.18)',
    backgroundColor: 'rgba(255,255,255,0.09)',
    paddingHorizontal: spacing.md,
  },
  accessory: { flex: 1, alignItems: 'flex-end', gap: spacing.xs },
  text: { maxWidth: '94%', gap: spacing.sm },
  eyebrow: {
    color: colors.white,
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 1.15,
    textTransform: 'uppercase',
  },
  title: { color: colors.white, fontSize: 29, lineHeight: 33, fontWeight: '900', letterSpacing: -0.5 },
  subtitle: { color: 'rgba(255,255,255,0.76)', fontSize: 13, lineHeight: 19 },
  accentLine: { width: 38, height: 4, borderRadius: radii.pill },
});
