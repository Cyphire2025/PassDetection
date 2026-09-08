import { LinearGradient } from 'expo-linear-gradient';
import ArrowUpRight from 'lucide-react-native/icons/arrow-up-right';
import Earth from 'lucide-react-native/icons/earth';
import Plane from 'lucide-react-native/icons/plane';
import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { moveAccessibilityFocus, useAccessibilityRouteFocus } from '@/design/accessibility/use-accessibility-route-focus';
import { useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { OfflineStatusChip } from '@/design/components/offline-status-chip';
import type { Trip } from '@/features/trips/model/trip';

import { useJourneyRoute } from '../hooks/use-journey-route';
import { GlobeSurface } from './globe-surface';
import { JourneyGlobeModal, type JourneyCardBounds } from './journey-globe-modal';

const GLOBE_SIZE = 246;

export const TripJourneyCard = memo(function TripJourneyCard({ trip, active }: { trip: Trip; active: boolean }) {
  const root = useRef<View>(null);
  const titleRef = useRef<Text>(null);
  const mounted = useRef(true);
  const openingGeneration = useRef(0);
  const [bounds, setBounds] = useState<JourneyCardBounds | null>(null);
  const [globeReady, setGlobeReady] = useState(false);
  const { route, status } = useJourneyRoute(trip, active);
  const reduceMotion = useReducedMotion();
  const title = trip.destination || trip.name;
  useAccessibilityRouteFocus(titleRef);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    openingGeneration.current += 1;
    if (!active) setBounds(null);
  }, [active]);
  const ready = useCallback(() => setGlobeReady(true), []);
  const failed = useCallback(() => setGlobeReady(false), []);
  const open = useCallback(() => {
    if (!active) return;
    const generation = ++openingGeneration.current;
    root.current?.measureInWindow((x, y, width, height) => {
      if (mounted.current && generation === openingGeneration.current && width > 0 && height > 0) {
        setBounds({ x, y, width, height, globeSize: GLOBE_SIZE });
      }
    });
  }, [active]);
  const close = useCallback(() => {
    setBounds(null);
    void moveAccessibilityFocus(titleRef.current);
  }, []);

  return (
    <>
      <View ref={root} collapsable={false}>
        <Pressable
          testID="trip-journey-card"
          accessibilityRole="button"
          accessibilityLabel={`Explore your journey to ${title}`}
          accessibilityHint={route ? `Opens an interactive globe with an illustrative route from ${route.origin.city} to ${route.destination.city}` : 'Opens an interactive world globe'}
          onPress={open}>
          <LinearGradient colors={['#092A3B', '#103F51', '#145166']} start={{ x: 0, y: 0 }} end={{ x: 1, y: 0.8 }} style={styles.card}>
            <View pointerEvents="none" accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={styles.globe}>
              {!globeReady ? <View style={styles.placeholder}><Earth size={173} strokeWidth={0.6} color="#446D7B" /></View> : null}
              <GlobeSurface route={route} mode="card" active={active && !bounds} reduceMotion={reduceMotion} onReady={ready} onError={failed} style={styles.fill} />
            </View>
            <LinearGradient pointerEvents="none" colors={['rgba(9,42,59,0.4)', 'rgba(9,42,59,0)']} start={{ x: 0, y: 0.5 }} end={{ x: 0.8, y: 0.5 }} style={StyleSheet.absoluteFill} />
            <View style={styles.top}>
              <View style={styles.eyebrowRow}><Plane color="#B8D5DF" size={13} /><Text style={styles.eyebrow}>MY TRIP</Text></View>
              <OfflineStatusChip />
            </View>
            <View style={styles.copy}>
              <Text ref={titleRef} accessibilityRole="header" numberOfLines={2} style={styles.title}>{title}</Text>
              <Text numberOfLines={2} style={styles.groupName}>{trip.name}</Text>
            </View>
            <View style={styles.bottom}>
              <View style={styles.routePill}>
                <View style={styles.dot} />
                <Text style={styles.routeText}>{route ? `${route.origin.iata ?? route.origin.city}  →  ${route.destination.iata ?? route.destination.city}` : 'Discover your destination'}</Text>
              </View>
              <View style={styles.explore}><Text style={styles.exploreText}>Explore</Text><ArrowUpRight color="#EDF4E8" size={16} /></View>
            </View>
          </LinearGradient>
        </Pressable>
      </View>
      {bounds ? <JourneyGlobeModal key={trip.id} bounds={bounds} route={route} lookupStatus={status} title={title} groupName={trip.name} reduceMotion={reduceMotion} onClose={close} /> : null}
    </>
  );
});

const styles = StyleSheet.create({
  card: { minHeight: 206, borderRadius: 26, padding: 23, overflow: 'hidden', gap: 22, borderWidth: 1, borderColor: '#28596A' },
  globe: { position: 'absolute', width: GLOBE_SIZE, height: GLOBE_SIZE, right: -28, top: '50%', marginTop: -GLOBE_SIZE / 2 },
  fill: { flex: 1 },
  placeholder: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, alignItems: 'center', justifyContent: 'center' },
  top: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 },
  eyebrowRow: { flexDirection: 'row', alignItems: 'center', gap: 7 },
  eyebrow: { color: '#D2E2E5', fontSize: 9, letterSpacing: 1.9, fontWeight: '800' },
  copy: { maxWidth: '74%', gap: 7 },
  title: { color: '#F8FAF8', fontSize: 31, lineHeight: 37, fontWeight: '800', letterSpacing: -0.8 },
  groupName: { color: '#CADDE1', fontSize: 12, lineHeight: 18, maxWidth: '89%' },
  bottom: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12, paddingTop: 2 },
  routePill: { flexShrink: 1, flexDirection: 'row', gap: 7, alignItems: 'center', borderRadius: 18, backgroundColor: 'rgba(7,33,46,0.7)', borderWidth: 1, borderColor: '#3E6572', paddingVertical: 7, paddingHorizontal: 10 },
  dot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#D0E77A' },
  routeText: { color: '#E1EBCE', fontSize: 10, letterSpacing: 1, fontWeight: '700', flexShrink: 1 },
  explore: { flexDirection: 'row', gap: 4, alignItems: 'center' },
  exploreText: { color: '#E3EBCF', fontSize: 11, fontWeight: '600' },
});
