import { Stack } from 'expo-router';

import { RoleGate } from '@/design/navigation/role-gate';
import { CoordinatorTripGuard } from '@/features/coordinator/ui/coordinator-trip-guard';

export default function CoordinatorLayout() {
  return (
    <RoleGate role="coordinator">
      <CoordinatorTripGuard>
        <Stack screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="operations/common-documents" />
          <Stack.Screen name="operations/incidents" />
          <Stack.Screen name="operations/updates" />
          <Stack.Screen name="operations/profile" />
          <Stack.Screen name="operations/passenger/[id]" />
        </Stack>
      </CoordinatorTripGuard>
    </RoleGate>
  );
}
