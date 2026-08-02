import { Redirect } from 'expo-router';
import type { PropsWithChildren } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import type { MobileRole } from '@/core/auth/types';
import { LoadingScreen } from '@/design/components/loading-screen';

export function RoleGate({ role, children }: PropsWithChildren<{ role: MobileRole }>) {
  const status = useSessionStore((state) => state.status);
  const session = useSessionStore((state) => state.session);

  if (status === 'booting') return <LoadingScreen label="Securing your trip" />;
  if (!session) return <Redirect href="/(auth)/welcome" />;
  if (session.principal.forcePasswordChange) return <Redirect href="/(auth)/change-password" />;
  if (session.principal.principalType !== role) return <Redirect href="/" />;
  return children;
}
