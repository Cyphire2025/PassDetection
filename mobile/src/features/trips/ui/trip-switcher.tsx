import { useCallback } from 'react';
import { FlatList, Pressable, StyleSheet, Text, type ListRenderItem } from 'react-native';

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
  const renderTrip = useCallback<ListRenderItem<Trip>>(({ item }) => {
    const selected = item.id === selectedTripId;
    return (
      <Pressable
        accessibilityRole="radio"
        accessibilityState={{ selected }}
        onPress={() => onSelect(item.id)}
        style={({ pressed }) => [styles.chip, selected && styles.selected, pressed && styles.pressed]}>
        <Text style={[styles.label, selected && styles.selectedLabel]}>{item.destination || item.name}</Text>
      </Pressable>
    );
  }, [onSelect, selectedTripId]);
  if (trips.length < 2) return null;
  return (
    <FlatList
      horizontal
      data={trips}
      keyExtractor={(trip) => trip.id}
      renderItem={renderTrip}
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
      initialNumToRender={6}
      maxToRenderPerBatch={8}
      windowSize={5}
    />
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
