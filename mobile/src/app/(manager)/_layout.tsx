import { Slot } from 'expo-router';

import { RoleGate } from '@/design/navigation/role-gate';

export default function ManagerLayout() {
  return (
    <RoleGate role="client_manager">
      <Slot />
    </RoleGate>
  );
}
