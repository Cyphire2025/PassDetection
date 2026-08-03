import { Redirect, router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useSessionStore } from '@/core/auth/session-store';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import {
  preloadAuthenticatedWorkspace,
  type RequiredPreloadProgress,
} from '@/core/sync/required-preload';
import { requiredPreparationRunKey } from '@/core/sync/required-preload-policy';
import { RequiredDownloadScreen } from '@/design/components/required-download-screen';
import { SafeSignOutButton } from '@/features/profile/ui/safe-sign-out-button';

const INITIAL_PROGRESS: RequiredPreloadProgress = {
  percent: 0,
  message: 'Preparing secure offline access',
  completedLabel: 'Starting download',
};

export default function RequiredPreparationScreen() {
  const session = useSessionStore((state) => state.session);
  const preparationRunKey = requiredPreparationRunKey(session);
  const [progress, setProgress] = useState(INITIAL_PROGRESS);
  const [error, setError] = useState<string | null>(null);
  const runId = useRef(0);

  const runPreparation = useCallback(async (currentRun: number) => {
    try {
      const result = await preloadAuthenticatedWorkspace((next) => {
        if (runId.current === currentRun) setProgress(next);
      });
      if (runId.current !== currentRun) return;
      router.replace(result.destination);
    } catch (caught) {
      if (runId.current !== currentRun) return;
      setError(userFacingErrorMessage(
        caught,
        'Required offline data could not be prepared. Try again.',
      ));
    }
  }, []);

  const retry = useCallback(() => {
    const currentRun = ++runId.current;
    setError(null);
    setProgress(INITIAL_PROGRESS);
    void runPreparation(currentRun);
  }, [runPreparation]);

  useEffect(() => {
    if (preparationRunKey) {
      const currentRun = ++runId.current;
      void runPreparation(currentRun);
    }
    return () => {
      runId.current += 1;
    };
  }, [preparationRunKey, runPreparation]);

  if (!session) return <Redirect href="/(auth)/welcome" />;
  return (
    <RequiredDownloadScreen
      message={progress.message}
      progress={progress.percent}
      completedLabel={progress.completedLabel}
      error={error}
      onRetry={retry}
      errorSecondaryAction={error ? <SafeSignOutButton label="Sign out and return to login" /> : null}
    />
  );
}
