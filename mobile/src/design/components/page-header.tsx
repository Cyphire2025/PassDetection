import { LinearGradient } from 'expo-linear-gradient';
import type { ReactNode } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

export type PageHeaderTone = 'passenger' | 'manager' | 'coordinator' | 'neutral';

const toneConfig = {
  passenger: {
    colors: [colors.navy, '#15596A', colors.blueDeep] as const,
    accent: colors.aqua,
  },
  manager: {
    colors: [colors.navy, '#174C66', '#295F87'] as const,
    accent: colors.blueSoft,
  },
  coordinator: {
    colors: [colors.navy, '#194A4A', '#4E5D25'] as const,
    accent: colors.green,
  },
  neutral: {
    colors: [colors.navy, colors.navySoft, colors.blueDeep] as const,
    accent: colors.aqua,
  },
} as const;

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
      <View pointerEvents="none" style={[styles.orb, { backgroundColor: config.accent }]} />
      <View pointerEvents="none" style={styles.ring} />
      <View style={styles.topRow}>
        <View style={styles.eyebrowPill}>
          <View style={[styles.roleMark, { borderColor: config.accent }]}>
            <View style={[styles.roleMarkCore, { backgroundColor: config.accent }]} />
          </View>
          <Text style={styles.eyebrow}>{eyebrow || 'Group Companion'}</Text>
        </View>
        {accessory ? <View style={styles.accessory}>{accessory}</View> : null}
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
    minHeight: 158,
    overflow: 'hidden',
    borderRadius: radii.lg,
    padding: spacing.xl,
    gap: spacing.lg,
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
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.md },
  eyebrowPill: {
    minHeight: 30,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.18)',
    backgroundColor: 'rgba(255,255,255,0.09)',
    paddingHorizontal: spacing.md,
  },
  roleMark: { width: 14, height: 14, borderRadius: 7, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  roleMarkCore: { width: 6, height: 6, borderRadius: 3 },
  accessory: { alignItems: 'flex-end' },
  text: { maxWidth: '92%', gap: spacing.xs },
  eyebrow: {
    color: colors.white,
    fontSize: 10,
    fontWeight: '900',
    letterSpacing: 1.15,
    textTransform: 'uppercase',
  },
  title: { color: colors.white, fontSize: 29, lineHeight: 34, fontWeight: '900', letterSpacing: -0.5 },
  subtitle: { color: 'rgba(255,255,255,0.76)', fontSize: 13, lineHeight: 19 },
  accentLine: { width: 38, height: 4, borderRadius: radii.pill },
});
