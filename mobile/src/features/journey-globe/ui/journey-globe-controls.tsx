import LocateFixed from 'lucide-react-native/icons/locate-fixed';
import Minus from 'lucide-react-native/icons/minus';
import Plus from 'lucide-react-native/icons/plus';
import { Pressable, StyleSheet, Text, View } from 'react-native';

type Props = { onZoomIn: () => void; onZoomOut: () => void; onReset: () => void };

export function JourneyGlobeControls({ onZoomIn, onZoomOut, onReset }: Props) {
  return (
    <View style={styles.root}>
      <Pressable accessibilityRole="button" accessibilityLabel="Zoom out on globe" onPress={onZoomOut} style={styles.icon}>
        <Minus color="#ECF5F7" size={21} />
      </Pressable>
      <View style={styles.divider} />
      <Pressable accessibilityRole="button" accessibilityLabel="Reset globe to your route" onPress={onReset} style={styles.reset}>
        <LocateFixed color="#C9E374" size={18} /><Text style={styles.text}>Your route</Text>
      </Pressable>
      <View style={styles.divider} />
      <Pressable accessibilityRole="button" accessibilityLabel="Zoom in on globe" onPress={onZoomIn} style={styles.icon}>
        <Plus color="#ECF5F7" size={21} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { alignSelf: 'center', flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderColor: '#315361', backgroundColor: '#123644', borderRadius: 28 },
  icon: { minWidth: 52, minHeight: 48, alignItems: 'center', justifyContent: 'center' },
  divider: { width: 1, height: 17, backgroundColor: '#3C5965' },
  reset: { minHeight: 48, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, paddingHorizontal: 17 },
  text: { color: '#E5EFF1', fontSize: 12, fontWeight: '600' },
});
