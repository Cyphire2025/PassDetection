import { onlineManager } from '@tanstack/react-query';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { env } from '@/core/config/env';
import { isDemoMode } from '@/core/demo/demo-mode';

import { ForegroundRealtimeClient, type RealtimeLifecycleState } from './realtime-client';

export function RealtimeRuntime() {
  const demoMode = isDemoMode();
  const sessionId = useSessionStore((state) => state.session?.sessionId ?? null);
  const accessToken = useSessionStore((state) => state.session?.accessToken ?? null);

  useEffect(() => {
    if (demoMode || !env.realtimeEnabled) return;

    const client = new ForegroundRealtimeClient();
    let foreground = AppState.currentState === 'active';
    let online = onlineManager.isOnline();
    const lifecycle = (): RealtimeLifecycleState => ({
      foreground,
      online,
      session: sessionId && accessToken ? { sessionId, accessToken } : null,
    });

    client.start(lifecycle());
    const appState = AppState.addEventListener('change', (state) => {
      foreground = state === 'active';
      client.updateLifecycle(lifecycle());
    });
    const network = onlineManager.subscribe((nextOnline) => {
      online = nextOnline;
      client.updateLifecycle(lifecycle());
    });

    return () => {
      network();
      appState.remove();
      client.stop();
    };
  }, [accessToken, demoMode, sessionId]);

  return null;
}
