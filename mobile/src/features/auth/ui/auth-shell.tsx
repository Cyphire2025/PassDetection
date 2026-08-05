import { LinearGradient } from 'expo-linear-gradient';
import type { PropsWithChildren } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { isDemoMode } from '@/core/demo/demo-mode';
import { AmbientHeroGlow } from '@/design/components/ambient-hero-glow';
import { BrandLogo } from '@/design/components/brand-logo';
import { GlassCard } from '@/design/components/glass-card';
import { HeroParticles } from '@/design/components/hero-particles';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
  centerContent = false,
  showBrandLogo = false,
}: PropsWithChildren<{
  eyebrow: string;
  title: string;
  description: string;
  centerContent?: boolean;
  showBrandLogo?: boolean;
}>) {
  return (
    <Screen contentStyle={[styles.screen, centerContent ? styles.centerContent : null]}>
      {showBrandLogo ? <View style={styles.centeredLogo}><BrandLogo /></View> : null}
      {isDemoMode() ? (
        <View accessibilityRole="text" style={styles.demoBanner}>
          <Text style={styles.demoText}>LOCAL EMULATOR DEMO · NO SERVER CONNECTION</Text>
        </View>
      ) : null}
      <LinearGradient
        colors={[colors.navy, '#164E61', colors.blueDeep]}
        style={[styles.hero, showBrandLogo ? styles.welcomeHero : null]}
      >
        <AmbientHeroGlow color={colors.aqua} style={styles.heroOrb} />
        <HeroParticles />
        <View style={styles.brandRow}>
          <View style={styles.eyebrowPill}><Text style={styles.eyebrow}>{eyebrow}</Text></View>
        </View>
        <Text accessibilityRole="header" style={styles.title}>{title}</Text>
        <Text style={styles.description}>{description}</Text>
        <View style={styles.heroAccent} />
      </LinearGradient>
      <GlassCard style={styles.card}>{children}</GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingTop: 48, gap: spacing.lg },
  centerContent: { paddingTop: 116 },
  centeredLogo: { alignItems: 'center', justifyContent: 'center' },
  welcomeHero: { marginTop: 14 },
  demoBanner: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    backgroundColor: colors.greenSoft,
    borderColor: colors.green,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  demoText: { color: colors.greenDeep, fontSize: 10, fontWeight: '900', letterSpacing: 0.7 },
  hero: {
    minHeight: 280,
    overflow: 'hidden',
    borderRadius: 30,
    padding: spacing.xl,
    justifyContent: 'flex-end',
    gap: spacing.md,
    shadowColor: colors.navy,
    shadowOpacity: 0.24,
    shadowRadius: 26,
    shadowOffset: { width: 0, height: 14 },
    elevation: 8,
  },
  heroOrb: {
    position: 'absolute',
    width: 190,
    height: 190,
    borderRadius: 95,
    right: -52,
    top: -72,
  },
  brandRow: { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.sm },
  eyebrowPill: { minHeight: 30, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.1)' },
  eyebrow: {
    color: colors.white,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    fontSize: 10,
    fontWeight: '900',
  },
  title: { color: colors.white, fontSize: 35, lineHeight: 40, fontWeight: '900', letterSpacing: -0.7 },
  description: { color: 'rgba(255,255,255,0.76)', fontSize: 15, lineHeight: 23, maxWidth: 340 },
  heroAccent: { width: 48, height: 5, borderRadius: 99, backgroundColor: colors.aqua },
  card: { gap: spacing.lg, marginBottom: spacing.xl },
});
