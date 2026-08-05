import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import type { PropsWithChildren } from 'react';
import { ScrollView, StyleSheet, View, type ScrollViewProps, type StyleProp, type ViewStyle } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { spacing } from '@/design/theme';

const wallpaperSource = require('../../../assets/images/wallpaper.png') as number;

type Props = PropsWithChildren<{
  scroll?: boolean;
  contentStyle?: StyleProp<ViewStyle>;
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
    <View style={styles.root}>
      <Image source={wallpaperSource} contentFit="cover" cachePolicy="memory-disk" style={styles.wallpaper} />
      <LinearGradient
        pointerEvents="none"
        colors={['rgba(238,248,250,0.18)', 'rgba(255,255,255,0.28)', 'rgba(238,245,246,0.2)']}
        style={StyleSheet.absoluteFill}
      />
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
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  wallpaper: { position: 'absolute', inset: 0 },
  fill: { flex: 1 },
  content: { paddingHorizontal: spacing.lg },
});
