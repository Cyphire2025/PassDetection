import Volume2 from 'lucide-react-native/icons/volume-2';
import VolumeX from 'lucide-react-native/icons/volume-x';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, radii, spacing } from '@/design/theme';

type Props = Readonly<{
  muted: boolean;
  busy: boolean;
  error: string | null;
  onToggle: () => void;
}>;

export function ScanFeedbackAudioToggle({ muted, busy, error, onToggle }: Props) {
  return (
    <View style={styles.container}>
      <Pressable
        accessibilityRole="switch"
        accessibilityState={{ checked: !muted, disabled: busy }}
        accessibilityLabel="Attendance scan sounds"
        accessibilityHint="Toggles persistent success, duplicate, and failure sounds"
        disabled={busy}
        onPress={onToggle}
        style={({ pressed }) => [styles.control, pressed && styles.pressed, busy && styles.busy]}>
        {muted
          ? <VolumeX color={colors.ink} size={20} />
          : <Volume2 color={colors.greenDeep} size={20} />}
        <Text style={styles.label}>{muted ? 'Sound off' : 'Sound on'}</Text>
      </Pressable>
      {error ? <Text accessibilityLiveRegion="polite" style={styles.error}>{error}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignItems: 'flex-end', gap: 3 },
  control: {
    minHeight: 44,
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  label: { color: colors.ink, fontSize: 13, fontWeight: '900' },
  error: { color: colors.danger, fontSize: 11, fontWeight: '700', maxWidth: 180, textAlign: 'right' },
  pressed: { opacity: 0.68 },
  busy: { opacity: 0.58 },
});
