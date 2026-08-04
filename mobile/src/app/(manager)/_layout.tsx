import { Stack } from 'expo-router';

import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { RoleGate } from '@/design/navigation/role-gate';

export default function ManagerLayout() {
  const reduceMotion = useReducedMotion();
  return (
    <RoleGate role="client_manager">
      <Stack screenOptions={{ headerShown: false, animation: navigationAnimation(reduceMotion, 'slide_from_right') }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="document/[id]" />
      </Stack>
    </RoleGate>
  );
}
