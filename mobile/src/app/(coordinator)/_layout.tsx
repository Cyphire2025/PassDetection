import { Stack } from 'expo-router';

import { navigationAnimation, useReducedMotion } from '@/design/accessibility/use-reduced-motion';
import { RoleGate } from '@/design/navigation/role-gate';
import { CoordinatorTripGuard } from '@/features/coordinator/ui/coordinator-trip-guard';

export default function CoordinatorLayout() {
  const reduceMotion = useReducedMotion();
  return (
    <RoleGate role="coordinator">
      <CoordinatorTripGuard>
        <Stack screenOptions={{ headerShown: false, animation: navigationAnimation(reduceMotion, 'slide_from_right') }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="operations/common-documents" />
          <Stack.Screen name="operations/incidents" />
          <Stack.Screen name="operations/updates" />
          <Stack.Screen name="operations/scan-issues" />
          <Stack.Screen name="operations/profile" />
          <Stack.Screen name="operations/passenger/[id]" />
          <Stack.Screen name="operations/document/[id]" />
        </Stack>
      </CoordinatorTripGuard>
    </RoleGate>
  );
}
