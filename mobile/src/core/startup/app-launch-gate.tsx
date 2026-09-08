import { Component, useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';
import { AccessibilityInfo, Animated, AppState, Easing, Image, Platform, StyleSheet, View, useWindowDimensions, type AppStateStatus, type LayoutChangeEvent } from 'react-native';

import { markApplicationInteractive } from '@/core/observability/mobile-observability';
import { ScreenBackdrop } from '@/design/components/screen-backdrop';

import { LaunchChoreographyContext } from './launch-choreography';
import { launchDockGeometry, type LaunchRect } from './launch-geometry';
import { LaunchVideo } from './launch-video';
import { hideNativeSplash } from './native-splash';

const launchPoster = require('../../../assets/images/global-connect-launch-logo-alpha.png') as number;
const supportsVideoBlend = Platform.OS !== 'android' || Number(Platform.Version) >= 29;

/** Keep the router mounted so session restoration and deep links run in parallel. */
export function AppLaunchGate({ appReady, children, welcomeExpected = false }: PropsWithChildren<{ appReady: boolean; welcomeExpected?: boolean }>) {
  const window = useWindowDimensions();
  const rootView = useRef<View>(null);
  const [rootRect, setRootRect] = useState<LaunchRect>({ x: 0, y: 0, width: window.width, height: window.height });
  const [logoTarget, setLogoTarget] = useState<LaunchRect | null>(null);
  const [targetWaitOver, setTargetWaitOver] = useState(false);
  const [motionComplete, setMotionComplete] = useState(
    () => AppState.currentState === 'background',
  );
  const [foreground, setForeground] = useState(() => AppState.currentState === 'active');
  const [nativeHidden, setNativeHidden] = useState(false);
  const [reduceMotion, setReduceMotion] = useState<boolean | null>(null);
  const [transitionComplete, setTransitionComplete] = useState(false);
  const [transition] = useState(() => new Animated.Value(0));
  const hidingNative = useRef(false);
  const interactiveMarked = useRef(false);
  const mounted = useRef(true);
  const showingLaunch = !transitionComplete;
  const dock = targetWaitOver ? null : launchDockGeometry(rootRect, logoTarget);
  const docking = welcomeExpected && dock !== null;
  const frameWidth = Math.min(rootRect.width, 720);
  const registerLogo = useCallback((bounds: LaunchRect | null) => {
    setLogoTarget((previous) => JSON.stringify(previous) === JSON.stringify(bounds) ? previous : bounds);
  }, []);
  const choreography = useMemo(() => ({ active: showingLaunch && welcomeExpected, progress: transition, registerLogo }),
    [registerLogo, showingLaunch, transition, welcomeExpected]);

  const completeMotion = useCallback(() => setMotionComplete(true), []);
  const revealLaunch = useCallback(() => {
    if (hidingNative.current) return;
    hidingNative.current = true;
    // Playback starts only once the native splash has handed off to this
    // already-laid-out white stage, so the beginning is not played underneath it.
    void hideNativeSplash().finally(() => {
      if (mounted.current) setNativeHidden(true);
    });
  }, []);
  const measureRoot = useCallback((event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    rootView.current?.measureInWindow((x, y) => setRootRect({ x, y, width, height }));
    revealLaunch();
  }, [revealLaunch]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  // Reduced motion or a lifecycle event can finish before the first layout
  // callback. They must still release the native splash instead of removing
  // the only view that could hand off from it.
  useEffect(() => {
    if (motionComplete && !nativeHidden) revealLaunch();
  }, [motionComplete, nativeHidden, revealLaunch]);

  useEffect(() => {
    let active = true;
    const applyPreference = (enabled: boolean) => {
      if (!active) return;
      setReduceMotion(enabled);
      if (enabled) completeMotion();
    };
    void AccessibilityInfo.isReduceMotionEnabled()
      .then(applyPreference)
      .catch(() => applyPreference(true));
    const preference = AccessibilityInfo.addEventListener('reduceMotionChanged', applyPreference);
    // The launch is a cold-start introduction. Leaving the app finishes it;
    // returning to an existing session never restarts or adds another wait.
    const applyLifecycle = (state: AppStateStatus | null) => {
      if (!active) return;
      setForeground(state === 'active');
      if (state === 'background') completeMotion();
    };
    const lifecycle = AppState.addEventListener('change', applyLifecycle);
    // iOS can start in inactive/unknown before entering the foreground. Wait
    // for active rather than treating that startup transition as a completed
    // intro; also reconcile a change between initial render and subscription.
    void Promise.resolve().then(() => applyLifecycle(AppState.currentState));
    // Allow a bounded decoder fallback without cutting the five-second clip.
    const watchdog = setTimeout(completeMotion, 12_000);
    return () => {
      active = false;
      clearTimeout(watchdog);
      preference.remove();
      lifecycle.remove();
    };
  }, [completeMotion]);

  useEffect(() => {
    if (!welcomeExpected || !motionComplete || !appReady || docking || targetWaitOver) return;
    // Allow the redirect's destination to lay out after session restoration.
    // Missing/offscreen targets still have a bounded normal fade fallback.
    const timeout = setTimeout(() => setTargetWaitOver(true), 650);
    return () => clearTimeout(timeout);
  }, [appReady, docking, motionComplete, targetWaitOver, welcomeExpected]);

  useEffect(() => {
    if (!motionComplete || !appReady || !nativeHidden || transitionComplete) return;
    let active = true;
    if (reduceMotion !== false || !foreground) {
      // Stop native work before settling a lifecycle/accessibility interruption.
      transition.stopAnimation(() => {
        if (!active) return;
        transition.setValue(1);
        setTransitionComplete(true);
      });
      return () => { active = false; };
    }
    if (welcomeExpected && !docking && !targetWaitOver) return;

    // Hold the last frame, dock the visible logo, and stagger the welcome cards.
    // Other destinations retain the normal crossfade without an invented target.
    const animation = Animated.timing(transition, {
      toValue: 1,
      duration: docking ? 1_050 : 650,
      delay: docking ? 160 : 0,
      easing: Easing.inOut(Easing.cubic),
      useNativeDriver: true,
      isInteraction: false,
    });
    animation.start(({ finished }) => {
      if (active && finished) setTransitionComplete(true);
    });
    return () => {
      active = false;
      animation.stop();
    };
  }, [appReady, docking, foreground, motionComplete, nativeHidden, reduceMotion, targetWaitOver, transition, transitionComplete, welcomeExpected]);

  useEffect(() => {
    if (showingLaunch || interactiveMarked.current) return;
    interactiveMarked.current = true;
    markApplicationInteractive();
  }, [showingLaunch]);

  return (
    <LaunchChoreographyContext.Provider value={choreography}>
    <View ref={rootView} collapsable={false} onLayout={measureRoot} style={styles.root}>
      <ScreenBackdrop />
      <Animated.View
        testID="app-launch-content"
        style={[styles.fill, { opacity: docking || transitionComplete ? 1 : transition }]}
        pointerEvents={showingLaunch ? 'none' : 'auto'}
        accessibilityElementsHidden={showingLaunch}
        importantForAccessibility={showingLaunch ? 'no-hide-descendants' : 'auto'}>
        {children}
      </Animated.View>
      {showingLaunch ? (
        <Animated.View
          testID="app-launch-screen"
          collapsable={false}
          style={[styles.stage, {
            width: frameWidth,
            height: frameWidth * 9 / 16,
            left: (rootRect.width - frameWidth) / 2,
            top: (rootRect.height - frameWidth * 9 / 16) / 2,
            mixBlendMode: !motionComplete && supportsVideoBlend ? 'multiply' : 'normal',
            opacity: docking ? 1 : transition.interpolate({ inputRange: [0, 1], outputRange: [1, 0] }),
            transform: docking && dock ? [
              { translateX: transition.interpolate({ inputRange: [0, 0.72, 1], outputRange: [0, dock.translateX, dock.translateX] }) },
              { translateY: transition.interpolate({ inputRange: [0, 0.72, 1], outputRange: [0, dock.translateY, dock.translateY] }) },
              { scale: transition.interpolate({ inputRange: [0, 0.72, 1], outputRange: [1, dock.scale, dock.scale] }) },
            ] : [],
          }]}
          onLayout={revealLaunch}
          accessibilityRole="image"
          accessibilityLabel="Global Connect Travels"
          accessibilityViewIsModal>
          <View style={styles.artwork} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
            <Image
              testID="launch-poster"
              source={launchPoster}
              resizeMode="contain"
              style={[styles.poster, !motionComplete && styles.hidden]}
            />
            {!motionComplete && reduceMotion === false ? (
              <LaunchVideoBoundary onFailure={completeMotion}>
                <LaunchVideo playing={nativeHidden && foreground} onComplete={completeMotion} />
              </LaunchVideoBoundary>
            ) : null}
          </View>
        </Animated.View>
      ) : null}
    </View>
    </LaunchChoreographyContext.Provider>
  );
}

/** Decoder/view construction failures affect decoration, never application access. */
class LaunchVideoBoundary extends Component<PropsWithChildren<{ onFailure: () => void }>, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  override componentDidCatch() { this.props.onFailure(); }
  override render() { return this.state.failed ? null : this.props.children; }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#FFFFFF', isolation: 'isolate' },
  fill: { flex: 1 },
  hidden: { opacity: 0 },
  stage: {
    position: 'absolute',
    zIndex: 1000,
    alignItems: 'center',
    justifyContent: 'center',
  },
  // The source has its own breathing room. Keep the complete landscape frame
  // centered on phones and tablets, without stretching or cropping the logo.
  artwork: { width: '100%', height: '100%' },
  poster: { width: '100%', height: '100%' },
});
