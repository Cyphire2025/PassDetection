import { LinearGradient } from 'expo-linear-gradient';
import ArrowLeft from 'lucide-react-native/icons/arrow-left';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, spacing } from '@/design/theme';

export function OperationHeader({ title, subtitle }: { title: string; subtitle: string }) {
  const router = useRouter();
  return (
    <LinearGradient colors={[colors.navy, '#15596A', colors.blueDeep]} style={styles.row}>
      <View pointerEvents="none" style={styles.orb} />
      <Pressable accessibilityRole="button" accessibilityLabel="Back" onPress={() => router.back()} style={styles.back}>
        <ArrowLeft color={colors.white} size={22} />
      </Pressable>
      <View style={styles.text}>
        <Text style={styles.title}>{title}</Text>
        <Text style={styles.subtitle}>{subtitle}</Text>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  row: { minHeight: 112, overflow: 'hidden', flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.lg, borderRadius: 26 },
  orb: { position: 'absolute', width: 120, height: 120, borderRadius: 60, backgroundColor: colors.aqua, opacity: 0.16, right: -38, top: -50 },
  back: { width: 48, height: 48, borderRadius: 24, backgroundColor: 'rgba(255,255,255,0.1)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.18)', alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: 2 },
  title: { color: colors.white, fontSize: 24, fontWeight: '900' },
  subtitle: { color: 'rgba(255,255,255,0.72)', fontSize: 12 },
});
