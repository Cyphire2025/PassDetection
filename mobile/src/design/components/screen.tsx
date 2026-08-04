import { LinearGradient } from 'expo-linear-gradient';
import type { PropsWithChildren } from 'react';
import { ScrollView, StyleSheet, View, type ScrollViewProps, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, spacing } from '@/design/theme';

type Props = PropsWithChildren<{
  scroll?: boolean;
  contentStyle?: ViewStyle;
  bottomInset?: number;
  scrollProps?: Omit<ScrollViewProps, 'contentContainerStyle'>;
}>;

export function Screen({ children, scroll = true, contentStyle, bottomInset = 24, scrollProps }: Props) {
  const insets = useSafeAreaInsets();
  const padding = {
    paddingTop: Math.max(insets.top, spacing.lg),
    paddingBottom: insets.bottom + bottomInset,
  };

  return (
    <LinearGradient colors={['#EEF8FA', '#F8FAF2', '#EEF5F6']} style={styles.root}>
      <View pointerEvents="none" style={styles.decorations}>
        <View style={[styles.glow, styles.blueGlow]} />
        <View style={[styles.glow, styles.greenGlow]} />
      </View>
      {scroll ? (
        <ScrollView
          {...scrollProps}
          keyboardShouldPersistTaps="handled"
          contentInsetAdjustmentBehavior="never"
          contentContainerStyle={[styles.content, padding, contentStyle]}>
          {children}
        </ScrollView>
      ) : (
        <View style={[styles.content, styles.fill, padding, contentStyle]}>{children}</View>
      )}
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  decorations: { position: 'absolute', inset: 0, overflow: 'hidden' },
  glow: { position: 'absolute', borderRadius: 999, opacity: 0.32 },
  blueGlow: { width: 240, height: 240, backgroundColor: colors.blueSoft, right: -126, top: 70 },
  greenGlow: { width: 210, height: 210, backgroundColor: colors.greenSoft, left: -126, bottom: 54 },
  fill: { flex: 1 },
  content: { paddingHorizontal: spacing.lg },
});
