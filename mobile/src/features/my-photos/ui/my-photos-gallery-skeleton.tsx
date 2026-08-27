import { StyleSheet, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { colors, radii, spacing } from '@/design/theme';

const SKELETON_ROWS = Object.freeze([
  Object.freeze([0.78, 1.24, 0.88]),
  Object.freeze([1.12, 0.82, 1.32]),
  Object.freeze([0.9, 1.18, 0.76]),
  Object.freeze([1.28, 0.84, 1.02]),
]);

export function MyPhotosGallerySkeleton() {
  const messages = useMessages();
  return (
    <View accessible accessibilityLabel={messages.loading()} style={styles.container}>
      {SKELETON_ROWS.map((row, rowIndex) => (
        <View key={rowIndex} style={styles.row}>
          {row.map((aspectRatio, columnIndex) => (
            <View
              key={`${rowIndex}:${columnIndex}`}
              style={[styles.tile, { aspectRatio }]}
            />
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.xs, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs },
  tile: { flex: 1, minHeight: 92, borderRadius: radii.sm, backgroundColor: colors.blueSoft },
});
