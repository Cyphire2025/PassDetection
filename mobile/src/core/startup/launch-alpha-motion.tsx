import { Image } from 'expo-image';
import { useEffect, useRef, useState } from 'react';
import { StyleSheet } from 'react-native';

const animationSource = require('../../../assets/videos/global-connect-launch-alpha.webp') as number;

/** Alpha fallback for Android 8/9, whose native views do not support blending. */
export function LaunchAlphaMotion({ playing, onComplete }: { playing: boolean; onComplete: () => void }) {
  const image = useRef<Image>(null);
  const remaining = useRef(5_000);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!playing || !ready) return;
    const started = Date.now();
    let active = true;
    void image.current?.startAnimating().catch(() => { if (active) onComplete(); });
    const timeout = setTimeout(onComplete, remaining.current);
    const currentImage = image.current;
    return () => {
      active = false;
      clearTimeout(timeout);
      remaining.current = Math.max(0, remaining.current - (Date.now() - started));
      void currentImage?.stopAnimating().catch(() => undefined);
    };
  }, [onComplete, playing, ready]);

  useEffect(() => {
    if (!playing || ready) return;
    const timeout = setTimeout(onComplete, 2_500);
    return () => clearTimeout(timeout);
  }, [onComplete, playing, ready]);

  return <Image ref={image} testID="launch-alpha-motion" source={animationSource} autoplay={false}
    contentFit="contain" transition={0} cachePolicy="memory" style={StyleSheet.absoluteFill}
    onLoad={() => setReady(true)} onError={onComplete} />;
}
