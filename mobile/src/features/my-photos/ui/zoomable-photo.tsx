import { Image, type ImageSource } from 'expo-image';
import { useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';

import { useMessages } from '@/core/localization/localization-provider';
import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { colors } from '@/design/theme';

import { photoPreviewAccessibilityLabel } from './photo-accessibility-copy';

type Props = Readonly<{
  source: ImageSource | null;
  recyclingKey: string;
  accessibilityLabel: string;
  privateLocal?: boolean;
}>;

export function ZoomablePhoto({
  source,
  recyclingKey,
  accessibilityLabel,
  privateLocal = false,
}: Props) {
  const messages = useMessages();
  const reduceMotion = useReducedMotion();
  const scale = useSharedValue(1);
  const startScale = useSharedValue(1);
  const pinch = useMemo(() => Gesture.Pinch()
    .onStart(() => {
      // Reanimated shared values are mutable worklet cells by design.
      // eslint-disable-next-line react-hooks/immutability
      startScale.value = scale.value;
    })
    .onUpdate((event) => {
      // eslint-disable-next-line react-hooks/immutability
      scale.value = Math.max(1, Math.min(4, startScale.value * event.scale));
    })
    .onEnd(() => {
      // eslint-disable-next-line react-hooks/immutability
      if (scale.value < 1.05) scale.value = withTiming(1, { duration: reduceMotion ? 0 : 120 });
    }), [reduceMotion, scale, startScale]);
  const doubleTap = useMemo(() => Gesture.Tap()
    .numberOfTaps(2)
    .maxDuration(260)
    .onEnd((_event, success) => {
      if (!success) return;
      // eslint-disable-next-line react-hooks/immutability
      scale.value = withTiming(scale.value > 1.05 ? 1 : 2, { duration: reduceMotion ? 0 : 160 });
    }), [reduceMotion, scale]);
  const composed = useMemo(() => Gesture.Simultaneous(pinch, doubleTap), [doubleTap, pinch]);
  const animatedStyle = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  return (
    <GestureDetector gesture={composed}>
      <Animated.View
        accessibilityLabel={photoPreviewAccessibilityLabel(
          Boolean(source),
          accessibilityLabel,
          messages.myPhotosPreviewUnavailable(),
        )}
        style={[styles.frame, animatedStyle]}>
        {source ? (
          <Image
            accessibilityIgnoresInvertColors
            cachePolicy={privateLocal ? 'none' : 'memory'}
            contentFit="contain"
            recyclingKey={recyclingKey}
            source={source}
            style={StyleSheet.absoluteFill}
          />
        ) : (
          <View style={styles.unavailable}>
            <Text style={styles.unavailableText}>{messages.myPhotosPreviewUnavailable()}</Text>
          </View>
        )}
      </Animated.View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1, overflow: 'hidden', backgroundColor: colors.navy },
  unavailable: { flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.navySoft },
  unavailableText: { color: colors.white, fontSize: 15, fontWeight: '800' },
});
