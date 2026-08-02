import { Stack } from 'expo-router';

import { RoleGate } from '@/design/navigation/role-gate';

export default function CoordinatorLayout() {
  return (
    <RoleGate role="coordinator">
      <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="operations/itinerary" />
        <Stack.Screen name="operations/rooming" />
        <Stack.Screen name="operations/meals" />
        <Stack.Screen name="operations/incidents" />
        <Stack.Screen name="operations/updates" />
        <Stack.Screen name="operations/profile" />
      </Stack>
    </RoleGate>
  );
}
