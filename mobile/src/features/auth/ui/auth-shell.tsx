import type { PropsWithChildren } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { isDemoMode } from '@/core/demo/demo-mode';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
}: PropsWithChildren<{ eyebrow: string; title: string; description: string }>) {
  return (
    <Screen contentStyle={styles.screen}>
      {isDemoMode() ? (
        <View accessibilityRole="text" style={styles.demoBanner}>
          <Text style={styles.demoText}>LOCAL EMULATOR DEMO · NO SERVER CONNECTION</Text>
        </View>
      ) : null}
      <View style={styles.brandMark} accessibilityElementsHidden>
        <View style={styles.brandInner} />
      </View>
      <Text style={styles.eyebrow}>{eyebrow}</Text>
      <Text accessibilityRole="header" style={styles.title}>
        {title}
      </Text>
      <Text style={styles.description}>{description}</Text>
      <GlassCard style={styles.card}>{children}</GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingTop: 72, gap: spacing.md },
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
  brandMark: {
    width: 52,
    height: 52,
    borderRadius: 18,
    backgroundColor: colors.blueSoft,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  brandInner: { width: 23, height: 23, borderRadius: 12, backgroundColor: colors.green },
  eyebrow: {
    color: colors.greenDeep,
    textTransform: 'uppercase',
    letterSpacing: 1.4,
    fontSize: 12,
    fontWeight: '800',
  },
  title: { color: colors.ink, fontSize: 35, lineHeight: 41, fontWeight: '800' },
  description: { color: colors.inkMuted, fontSize: 16, lineHeight: 24, marginBottom: spacing.lg },
  card: { gap: spacing.lg },
});
