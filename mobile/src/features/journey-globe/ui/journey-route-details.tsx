import ArrowRight from 'lucide-react-native/icons/arrow-right';
import Plane from 'lucide-react-native/icons/plane';
import { Linking, StyleSheet, Text, View } from 'react-native';

import type { JourneyRoute } from '../model/journey-route';
import type { JourneyLookupStatus } from '../model/journey-destination';

export function JourneyRouteDetails({ route, lookupStatus }: { route: JourneyRoute | null; lookupStatus?: JourneyLookupStatus | undefined }) {
  if (!route) {
    return (
      <View style={styles.panel}>
        <Text style={styles.heading}>A world to discover</Text>
        <Text style={styles.note}>
          {lookupStatus === 'resolving' ? 'Locating your group’s destination. Your route will appear here shortly.'
            : lookupStatus === 'ambiguous' ? 'The destination matches more than one place. Your travel team can clarify the location in the group details.'
              : 'Explore the globe. A route preview will appear when the destination lookup is available.'}
        </Text>
      </View>
    );
  }
  return (
    <View style={styles.panel} testID="journey-route-details">
      <View style={styles.eyebrowRow}>
        <Text style={styles.eyebrow}>YOUR JOURNEY</Text>
        <Text style={styles.distance}>≈ {Math.round(route.distanceKm).toLocaleString('en-IN')} km</Text>
      </View>
      <View style={styles.endpoints}>
        <View style={styles.endpoint}>
          <Text style={styles.code}>{route.origin.iata ?? route.origin.countryCode}</Text>
          <Text style={styles.city}>{route.origin.city}</Text>
          <Text style={styles.country}>{route.origin.country}</Text>
        </View>
        <View accessible={false} style={styles.connector}>
          <View style={styles.line} /><Plane color="#CCE66D" size={24} /><ArrowRight color="#70A2AF" size={17} />
        </View>
        <View style={[styles.endpoint, styles.arrival]}>
          <Text style={[styles.code, styles.arrivalCode]}>{route.destination.iata ?? route.destination.countryCode}</Text>
          <Text style={styles.city}>{route.destination.city}</Text>
          <Text style={styles.country}>{route.destination.country}</Text>
        </View>
      </View>
      <View style={styles.separator} />
      <Text style={styles.note}>
        {route.kind === 'illustrative'
          ? 'Illustrative route · From Delhi to your group’s destination. Your confirmed flight may differ.'
          : 'Route overview · The moving aircraft illustrates the journey and is not live flight tracking.'}
      </Text>
      {route.attribution ? <Text accessibilityRole="link" onPress={() => { void Linking.openURL('https://www.openstreetmap.org/copyright').catch(() => undefined); }} style={styles.attribution}>{route.attribution}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: { borderRadius: 24, backgroundColor: '#102F40', borderWidth: 1, borderColor: '#244657', padding: 21, gap: 18 },
  eyebrowRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 12 },
  eyebrow: { color: '#A9C4CB', fontSize: 10, letterSpacing: 2, fontWeight: '800' },
  distance: { color: '#BBD879', fontSize: 12, fontWeight: '600' },
  endpoints: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  endpoint: { flex: 1, gap: 3 },
  arrival: { alignItems: 'flex-end' },
  code: { color: '#F4F8F7', fontSize: 32, letterSpacing: -1, fontWeight: '800' },
  arrivalCode: { color: '#CEE877' },
  city: { color: '#EDF5F5', fontSize: 14, fontWeight: '600' },
  country: { color: '#A5BDC6', fontSize: 11 },
  connector: { flexDirection: 'row', alignItems: 'center', gap: 9, width: 74 },
  line: { flex: 1, height: 1, backgroundColor: '#597989' },
  separator: { height: 1, backgroundColor: '#2A4959' },
  heading: { color: '#F4F8F7', fontSize: 20, fontWeight: '700' },
  note: { color: '#B1C6CE', fontSize: 11, lineHeight: 17 },
  attribution: { color: '#93AFB8', fontSize: 10 },
});
