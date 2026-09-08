import { LinearGradient } from 'expo-linear-gradient';
import { StatusBar } from 'expo-status-bar';
import X from 'lucide-react-native/icons/x';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, { Easing, interpolate, runOnJS, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { moveAccessibilityFocus } from '@/design/accessibility/use-accessibility-route-focus';

import type { JourneyRoute } from '../model/journey-route';
import type { JourneyLookupStatus } from '../model/journey-destination';
import { GlobeSurface, type GlobeSurfaceHandle } from './globe-surface';
import { JourneyGlobeControls } from './journey-globe-controls';
import { JourneyRouteDetails } from './journey-route-details';

export type JourneyCardBounds = { x: number; y: number; width: number; height: number; globeSize: number };
type Props = { bounds: JourneyCardBounds; route: JourneyRoute | null; lookupStatus?: JourneyLookupStatus; title: string; groupName: string; reduceMotion: boolean; onClose: () => void };

export function JourneyGlobeModal({ bounds, route, lookupStatus, title, groupName, reduceMotion, onClose }: Props) {
  const window = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const globe = useRef<GlobeSurfaceHandle>(null);
  const heading = useRef<Text>(null);
  const [ready, setReady] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);
  const closing = useRef(false);
  const initialized = useRef(false);
  const progress = useSharedValue(0);
  const globeSize = Math.min(window.width, 600, Math.max(240, window.height * 0.47));
  const globeTop = Math.max(insets.top + 122, (window.height - globeSize) * 0.3);
  const globeLeft = (window.width - globeSize) / 2;
  const duration = reduceMotion ? 0 : 540;

  const finishExpansion = useCallback(() => {
    setExpanded(true);
    void moveAccessibilityFocus(heading.current);
  }, []);
  const markReady = useCallback(() => { initialized.current = true; setFailed(false); setReady(true); }, []);
  const markFailed = useCallback(() => { setFailed(true); setReady(true); }, []);
  useEffect(() => {
    // The fallback also opens the route details if a device cannot create a GL context.
    const timer = setTimeout(() => { if (!initialized.current) markFailed(); }, 1_500);
    return () => clearTimeout(timer);
  }, [markFailed]);
  useEffect(() => {
    if (!ready || closing.current) return;
    progress.set(withTiming(1, { duration, easing: Easing.bezier(0.2, 0.8, 0.2, 1) }, (finished) => {
      if (finished) runOnJS(finishExpansion)();
    }));
  }, [duration, finishExpansion, progress, ready]);

  const close = useCallback(() => {
    if (closing.current) return;
    closing.current = true;
    setExpanded(false);
    progress.set(withTiming(0, { duration: reduceMotion ? 0 : 380, easing: Easing.inOut(Easing.cubic) }, (finished) => {
      if (finished) runOnJS(onClose)();
    }));
  }, [onClose, progress, reduceMotion]);
  const frameStyle = useAnimatedStyle(() => ({
    top: interpolate(progress.value, [0, 1], [bounds.y, 0]),
    left: interpolate(progress.value, [0, 1], [bounds.x, 0]),
    width: interpolate(progress.value, [0, 1], [bounds.width, window.width]),
    height: interpolate(progress.value, [0, 1], [bounds.height, window.height]),
    borderRadius: interpolate(progress.value, [0, 1], [26, 0]),
  }));
  const globeStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(progress.value, [0, 1], [bounds.width - bounds.globeSize / 2 + 28 - globeSize / 2, globeLeft]) },
      { translateY: interpolate(progress.value, [0, 1], [bounds.height / 2 - globeSize / 2, globeTop]) },
      { scale: interpolate(progress.value, [0, 1], [bounds.globeSize / globeSize, 1]) },
    ],
  }));
  const contentStyle = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 0.42, 1], [0, 0, 1]),
    transform: [{ translateY: interpolate(progress.value, [0, 1], [30, 0]) }],
  }));
  const cardCopyStyle = useAnimatedStyle(() => ({ opacity: interpolate(progress.value, [0, 0.3, 1], [1, 0, 0]) }));

  return (
    <Modal transparent visible animationType="none" statusBarTranslucent navigationBarTranslucent onRequestClose={close}>
      <StatusBar style="light" />
      <GestureHandlerRootView style={styles.root}>
        <Animated.View accessibilityViewIsModal style={[styles.frame, frameStyle]}>
          <LinearGradient colors={['#081E2B', '#102F42', '#081F2D']} style={StyleSheet.absoluteFill} />
          <Animated.View style={[styles.globe, { width: globeSize, height: globeSize }, globeStyle]}>
            <GlobeSurface ref={globe} route={route} mode="expanded" active reduceMotion={reduceMotion} onReady={markReady} onError={markFailed} style={styles.fill} />
          </Animated.View>
          <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={[styles.initialCopy, cardCopyStyle]}>
            <Text style={styles.eyebrow}>MY TRIP</Text>
            <Text style={styles.initialTitle}>{title}</Text>
            <Text numberOfLines={1} style={styles.groupName}>{groupName}</Text>
          </Animated.View>
          <Animated.View pointerEvents={expanded ? 'box-none' : 'none'} accessibilityElementsHidden={!expanded} importantForAccessibility={expanded ? 'auto' : 'no-hide-descendants'} style={[StyleSheet.absoluteFill, contentStyle]}>
            <View style={[styles.header, { paddingTop: insets.top + 18 }]}>
              <View style={styles.headerCopy}>
                <Text style={styles.eyebrow}>A LITTLE CLOSER TO YOUR WORLD</Text>
                <Text ref={heading} accessibilityRole="header" style={styles.title}>{title}</Text>
                <Text numberOfLines={1} style={styles.groupName}>{groupName}</Text>
              </View>
              <Pressable testID="journey-globe-close" accessibilityRole="button" accessibilityLabel="Close journey globe" onPress={close} style={styles.close}>
                <X color="#EFF5F5" size={22} />
              </Pressable>
            </View>
            <View pointerEvents="none" style={[styles.gestureHint, { top: globeTop + globeSize - 15 }]}>
              <Text style={styles.hint}>{failed ? 'Globe unavailable on this device · Route details below' : 'Drag to explore  ·  Pinch to zoom'}</Text>
            </View>
            <ScrollView showsVerticalScrollIndicator={false} style={[styles.details, { top: globeTop + globeSize + 17 }]} contentContainerStyle={{ gap: 18, paddingBottom: Math.max(insets.bottom, 16) + 12 }}>
              {!failed ? <JourneyGlobeControls onZoomIn={() => globe.current?.zoomIn()} onZoomOut={() => globe.current?.zoomOut()} onReset={() => globe.current?.resetView()} /> : null}
              <JourneyRouteDetails route={route} lookupStatus={lookupStatus} />
            </ScrollView>
          </Animated.View>
        </Animated.View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  frame: { position: 'absolute', overflow: 'hidden', backgroundColor: '#0C2B3D' },
  globe: { position: 'absolute', top: 0, left: 0 },
  fill: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 14, paddingHorizontal: 24 },
  headerCopy: { flex: 1, gap: 7 },
  eyebrow: { fontSize: 9, letterSpacing: 1.75, fontWeight: '800', color: '#B6CFD6' },
  title: { color: '#F7F9F8', fontSize: 33, lineHeight: 40, fontWeight: '800', letterSpacing: -0.8 },
  groupName: { color: '#AFC9D2', fontSize: 12, lineHeight: 18 },
  close: { minWidth: 46, minHeight: 46, justifyContent: 'center', alignItems: 'center', borderRadius: 23, backgroundColor: '#193847', borderWidth: 1, borderColor: '#365260' },
  gestureHint: { position: 'absolute', left: 16, right: 16, alignItems: 'center' },
  hint: { color: '#AAC2CA', fontSize: 11, textAlign: 'center' },
  details: { position: 'absolute', left: 20, right: 20, bottom: 0 },
  initialCopy: { position: 'absolute', top: 25, left: 24, right: 100, gap: 13 },
  initialTitle: { color: '#F7F9F8', fontSize: 30, fontWeight: '800', marginTop: 12 },
});
