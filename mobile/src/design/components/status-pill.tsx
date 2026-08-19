import { StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

export function StatusPill({ label, tone = 'neutral' }: { label: string; tone?: 'good' | 'warning' | 'neutral' }) {
  return (
    <View
      accessibilityLabel={label}
      accessibilityRole="text"
      style={[styles.pill, tone === 'good' && styles.good, tone === 'warning' && styles.warning]}>
      <View
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        style={[styles.dot, tone === 'good' && styles.goodDot, tone === 'warning' && styles.warningDot]}
      />
      <Text style={styles.label}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    alignSelf: 'flex-start',
    minHeight: 30,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    backgroundColor: colors.blueSoft,
    borderRadius: radii.pill,
    paddingHorizontal: spacing.md,
  },
  good: { backgroundColor: colors.greenSoft },
  warning: { backgroundColor: '#FFF0D5' },
  dot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.blue },
  goodDot: { backgroundColor: colors.greenDeep },
  warningDot: { backgroundColor: colors.warning },
  label: { flexShrink: 1, color: colors.ink, fontSize: 12, lineHeight: 17, fontWeight: '700' },
});
