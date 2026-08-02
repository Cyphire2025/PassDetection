import { LinearGradient } from 'expo-linear-gradient';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '@/design/theme';

export function LoadingScreen({ label }: { label: string }) {
  return (
    <LinearGradient colors={['#F6FCFF', colors.greenWash]} style={styles.root}>
      <View accessibilityRole="progressbar" accessibilityLabel={label} style={styles.card}>
        <ActivityIndicator color={colors.greenDeep} size="large" />
        <Text style={styles.label}>{label}</Text>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  card: { alignItems: 'center', gap: spacing.lg },
  label: { color: colors.inkMuted, fontSize: 16, fontWeight: '600' },
});
