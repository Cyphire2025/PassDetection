import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

export function navigationAnimation<T extends string>(
  reduceMotion: boolean,
  animation: T,
): T | 'none' {
  return reduceMotion ? 'none' : animation;
}

export function useReducedMotion(): boolean {
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let active = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (active) setReduceMotion(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduceMotion);
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  return reduceMotion;
}
