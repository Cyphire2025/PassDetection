import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

import type { Trip } from '../model/trip';

export function TripSwitcher({
  trips,
  selectedTripId,
  onSelect,
}: {
  trips: Trip[];
  selectedTripId: string | null;
  onSelect: (tripId: string) => void;
}) {
  if (trips.length < 2) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.row}>
      {trips.map((trip) => {
        const selected = trip.id === selectedTripId;
        return (
          <Pressable
            key={trip.id}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => onSelect(trip.id)}
            style={({ pressed }) => [styles.chip, selected && styles.selected, pressed && styles.pressed]}>
            <Text style={[styles.label, selected && styles.selectedLabel]}>{trip.destination || trip.name}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: spacing.sm, paddingVertical: spacing.xs },
  chip: {
    minHeight: 40,
    justifyContent: 'center',
    borderRadius: radii.pill,
    backgroundColor: colors.surfaceStrong,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.lg,
  },
  selected: { backgroundColor: colors.greenSoft, borderColor: colors.green },
  pressed: { opacity: 0.65 },
  label: { color: colors.inkMuted, fontSize: 13, fontWeight: '700' },
  selectedLabel: { color: colors.greenDeep },
});
