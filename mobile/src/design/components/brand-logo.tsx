import { Image } from 'expo-image';
import { StyleSheet, View } from 'react-native';

const brandLogoSource = require('../../../assets/images/global-connect-logo.png') as number;

export function BrandLogo() {
  return (
    <View accessibilityLabel="Global Connect Travels" accessibilityRole="image" style={styles.frame}>
      <Image
        source={brandLogoSource}
        contentFit="contain"
        cachePolicy="memory-disk"
        style={styles.image}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    width: 142,
    height: 48,
    overflow: 'hidden',
  },
  image: {
    position: 'absolute',
    width: 196,
    height: 131,
    left: -27,
    top: -45,
  },
});
