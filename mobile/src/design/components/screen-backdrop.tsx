import { Image } from 'expo-image';
import { LinearGradient } from 'expo-linear-gradient';
import { StyleSheet, View } from 'react-native';

const wallpaperSource = require('../../../assets/images/wallpaper.png') as number;

/** Shared by the app surface and launch stage so the wallpaper never changes. */
export function ScreenBackdrop() {
  return (
    <View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.root]}>
      <Image source={wallpaperSource} contentFit="cover" cachePolicy="memory-disk" style={StyleSheet.absoluteFill} />
      <LinearGradient
        pointerEvents="none"
        colors={['rgba(238,248,250,0.18)', 'rgba(255,255,255,0.28)', 'rgba(238,245,246,0.2)']}
        style={StyleSheet.absoluteFill}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { backgroundColor: '#FFFFFF' },
});
