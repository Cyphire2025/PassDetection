import { Redirect } from 'expo-router';

import { useSessionStore } from '@/core/auth/session-store';
import { isRequiredPreparationActive } from '@/core/sync/required-preparation-lease';
import { LoadingScreen } from '@/design/components/loading-screen';

export default function Index() {
  const status = useSessionStore((state) => state.status);
  const session = useSessionStore((state) => state.session);

  if (status === 'booting') return <LoadingScreen label="Preparing your trips" />;
  if (!session) return <Redirect href="/(auth)/welcome" />;
  if (session.principal.forcePasswordChange) {
    return <Redirect href="/(auth)/change-password" />;
  }
  if (isRequiredPreparationActive(session.sessionId)) {
    return <Redirect href="/(auth)/prepare" />;
  }

  switch (session.principal.principalType) {
    case 'passenger':
      return <Redirect href="/(passenger)/(tabs)/trip" />;
    case 'client_manager':
      return <Redirect href="/(manager)/(tabs)/groups" />;
    case 'coordinator':
      return <Redirect href="/(coordinator)/(tabs)/groups" />;
  }
}
