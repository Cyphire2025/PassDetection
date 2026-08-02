import { Slot } from 'expo-router';

import { RoleGate } from '@/design/navigation/role-gate';

export default function PassengerLayout() {
  return (
    <RoleGate role="passenger">
      <Slot />
    </RoleGate>
  );
}
