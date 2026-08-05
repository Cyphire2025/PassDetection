import { Stack } from 'expo-router';

import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';

export default function AuthLayout() {
  const reduceMotion = useReducedMotion();
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        animation: navigationAnimation(reduceMotion, 'fade_from_bottom'),
        animationDuration: reduceMotion ? 0 : 210,
      }}
    />
  );
}
