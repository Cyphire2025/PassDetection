import { LinearGradient } from 'expo-linear-gradient';
import { StatusBar } from 'expo-status-bar';
import Earth from 'lucide-react-native/icons/earth';
import X from 'lucide-react-native/icons/x';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, { cancelAnimation, Easing, interpolate, runOnJS, useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated';
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
  const mounted = useRef(true);
  const closing = useRef(false);
  const shown = useRef(false);
  const initialized = useRef(false);
  const fallbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const progress = useSharedValue(0);
  const globeSize = Math.min(window.width, 600, Math.max(240, window.height * 0.47));
  const globeTop = Math.max(insets.top + 122, (window.height - globeSize) * 0.3);
  const globeLeft = (window.width - globeSize) / 2;
  const duration = reduceMotion ? 0 : 540;

  const clearFallback = useCallback(() => {
    if (fallbackTimer.current !== null) clearTimeout(fallbackTimer.current);
    fallbackTimer.current = null;
  }, []);
  const finishExpansion = useCallback(() => {
    if (!mounted.current || closing.current) return;
    setExpanded(true);
    void moveAccessibilityFocus(heading.current);
  }, []);
  const markReady = useCallback(() => {
    if (!mounted.current || closing.current) return;
    clearFallback();
    initialized.current = true;
    setFailed(false);
    setReady(true);
  }, [clearFallback]);
  const markFailed = useCallback(() => {
    if (!mounted.current || closing.current) return;
    clearFallback();
    setFailed(true);
    setReady(false);
  }, [clearFallback]);
  const markReleased = useCallback(() => {
    if (!mounted.current || closing.current) return;
    clearFallback();
    initialized.current = false;
    setReady(false);
    setFailed(false);
  }, [clearFallback]);
  const markLoading = useCallback(() => {
    markReleased();
    if (mounted.current && shown.current && !closing.current) {
      fallbackTimer.current = setTimeout(markFailed, 1_500);
    }
  }, [markFailed, markReleased]);
  const finishClose = useCallback(() => {
    if (mounted.current) onClose();
  }, [onClose]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearFallback();
      cancelAnimation(progress);
    };
  }, [clearFallback, progress]);
  const open = useCallback(() => {
    if (shown.current || closing.current || !mounted.current) return;
    shown.current = true;
    // Native presentation starts the transition. GPU readiness must never hold
    // the card still or replay its expansion when a late context arrives.
    progress.set(withTiming(1, { duration, easing: Easing.bezier(0.2, 0.8, 0.2, 1) }, (finished) => {
      if (finished) runOnJS(finishExpansion)();
    }));
    if (!initialized.current) fallbackTimer.current = setTimeout(markFailed, 1_500);
  }, [duration, finishExpansion, markFailed, progress]);

  const close = useCallback(() => {
    if (closing.current) return;
    closing.current = true;
    clearFallback();
    setExpanded(false);
    if (!shown.current) { onClose(); return; }
    progress.set(withTiming(0, { duration: reduceMotion ? 0 : 380, easing: Easing.inOut(Easing.cubic) }, (finished) => {
      if (finished) runOnJS(finishClose)();
    }));
  }, [clearFallback, finishClose, onClose, progress, reduceMotion]);
  const frameStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(progress.value, [0, 1], [bounds.x + bounds.width / 2 - window.width / 2, 0]) },
      { translateY: interpolate(progress.value, [0, 1], [bounds.y + bounds.height / 2 - window.height / 2, 0]) },
      { scaleX: interpolate(progress.value, [0, 1], [bounds.width / window.width, 1]) },
      { scaleY: interpolate(progress.value, [0, 1], [bounds.height / window.height, 1]) },
    ],
    borderRadius: interpolate(progress.value, [0, 1], [26, 0]),
  }));
  // Cancel the clipping frame's transform for its content. Both views retain
  // full-window layout; only compositor transforms change during expansion.
  const sceneStyle = useAnimatedStyle(() => ({
    transform: [
      { scaleX: 1 / interpolate(progress.value, [0, 1], [bounds.width / window.width, 1]) },
      { scaleY: 1 / interpolate(progress.value, [0, 1], [bounds.height / window.height, 1]) },
      { translateX: -interpolate(progress.value, [0, 1], [bounds.x + bounds.width / 2 - window.width / 2, 0]) },
      { translateY: -interpolate(progress.value, [0, 1], [bounds.y + bounds.height / 2 - window.height / 2, 0]) },
    ],
  }));
  const globeStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: interpolate(progress.value, [0, 1], [bounds.x + bounds.width - bounds.globeSize / 2 + 28 - globeSize / 2, globeLeft]) },
      { translateY: interpolate(progress.value, [0, 1], [bounds.y + bounds.height / 2 - globeSize / 2, globeTop]) },
      { scale: interpolate(progress.value, [0, 1], [bounds.globeSize / globeSize, 1]) },
    ],
  }));
  const contentStyle = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 0.42, 1], [0, 0, 1]),
    transform: [{ translateY: interpolate(progress.value, [0, 1], [30, 0]) }],
  }));
  const cardCopyStyle = useAnimatedStyle(() => ({ opacity: interpolate(progress.value, [0, 0.3, 1], [1, 0, 0]) }));

  return (
    <Modal testID="journey-globe-modal" transparent visible animationType="none" statusBarTranslucent navigationBarTranslucent onShow={open} onRequestClose={close}>
      <StatusBar style="light" />
      <GestureHandlerRootView accessibilityViewIsModal style={styles.root}>
        <Animated.View style={[styles.frame, { width: window.width, height: window.height }, frameStyle]}>
          <LinearGradient colors={['#081E2B', '#102F42', '#081F2D']} style={StyleSheet.absoluteFill} />
          <Animated.View style={[StyleSheet.absoluteFill, sceneStyle]}>
          <Animated.View style={[styles.globe, { width: globeSize, height: globeSize }, globeStyle]}>
            {!ready ? <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={styles.placeholder}><Earth size={globeSize * 0.7} strokeWidth={0.6} color="#446D7B" /></View> : null}
            <GlobeSurface ref={globe} route={route} mode="expanded" active paused={!expanded} reduceMotion={reduceMotion} onReady={markReady} onError={markFailed} onRelease={markReleased} onLoading={markLoading} style={styles.fill} />
          </Animated.View>
          <Animated.View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={[styles.initialCopy, { top: bounds.y + 25, left: bounds.x + 24, width: Math.max(0, bounds.width - 124) }, cardCopyStyle]}>
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
            </View>
            <View pointerEvents="none" style={[styles.gestureHint, { top: globeTop + globeSize - 15 }]}>
              <Text style={styles.hint}>{failed ? 'Globe unavailable on this device · Route details below' : ready ? 'Drag to explore  ·  Pinch to zoom' : 'Preparing your globe…'}</Text>
            </View>
            <ScrollView showsVerticalScrollIndicator={false} style={[styles.details, { top: globeTop + globeSize + 17 }]} contentContainerStyle={{ gap: 18, paddingBottom: Math.max(insets.bottom, 16) + 12 }}>
              {ready ? <JourneyGlobeControls onZoomIn={() => globe.current?.zoomIn()} onZoomOut={() => globe.current?.zoomOut()} onReset={() => globe.current?.resetView()} /> : null}
              <JourneyRouteDetails route={route} lookupStatus={lookupStatus} />
            </ScrollView>
          </Animated.View>
          </Animated.View>
        </Animated.View>
        <Pressable testID="journey-globe-close" accessibilityRole="button" accessibilityLabel="Close journey globe" onPress={close} style={[styles.close, { top: insets.top + 18 }]}>
          <X color="#EFF5F5" size={22} />
        </Pressable>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  frame: { position: 'absolute', top: 0, left: 0, overflow: 'hidden', backgroundColor: '#0C2B3D' },
  globe: { position: 'absolute', top: 0, left: 0 },
  fill: { flex: 1 },
  placeholder: { ...StyleSheet.absoluteFill, alignItems: 'center', justifyContent: 'center' },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 14, paddingLeft: 24, paddingRight: 84 },
  headerCopy: { flex: 1, gap: 7 },
  eyebrow: { fontSize: 9, letterSpacing: 1.75, fontWeight: '800', color: '#B6CFD6' },
  title: { color: '#F7F9F8', fontSize: 33, lineHeight: 40, fontWeight: '800', letterSpacing: -0.8 },
  groupName: { color: '#AFC9D2', fontSize: 12, lineHeight: 18 },
  close: { position: 'absolute', right: 24, minWidth: 46, minHeight: 46, justifyContent: 'center', alignItems: 'center', borderRadius: 23, backgroundColor: '#193847', borderWidth: 1, borderColor: '#365260' },
  gestureHint: { position: 'absolute', left: 16, right: 16, alignItems: 'center' },
  hint: { color: '#AAC2CA', fontSize: 11, textAlign: 'center' },
  details: { position: 'absolute', left: 20, right: 20, bottom: 0 },
  initialCopy: { position: 'absolute', gap: 13 },
  initialTitle: { color: '#F7F9F8', fontSize: 30, fontWeight: '800', marginTop: 12 },
});
