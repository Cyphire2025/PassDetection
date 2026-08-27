import * as Haptics from 'expo-haptics';
import { CameraView } from 'expo-camera';
import { router, useNavigation } from 'expo-router';
import ChevronLeft from 'lucide-react-native/icons/chevron-left';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { useMessages } from '@/core/localization/localization-provider';
import { recordMobileMetric } from '@/core/observability/mobile-observability';
import { ContentLoading } from '@/design/components/content-state';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

import { useFaceScanController } from '../hooks/use-face-scan-controller';
import { faceScanCloseDecision } from '../liveness/face-scan-navigation-policy';
import type { FaceScanChallengeMode } from '../model/face-scan-machine';
import { FaceScanRunningSurface } from './face-scan-running-surface';
import { faceScanCapabilityBlock } from './face-scan-capability-policy';
import { FaceScanStepContent } from './face-scan-step-content';
import {
  myPhotosRequestErrorPresentation,
  myPhotosUnavailablePresentation,
} from './my-photos-request-state';
import { MyPhotosStatusPanel } from './my-photos-status-panel';

export function FaceScanScreen() {
  const messages = useMessages();
  const trips = useTrips();
  const tripId = trips.selectedTripId;
  const navigation = useNavigation();
  const controller = useFaceScanController(tripId);
  const [busy, setBusy] = useState(false);
  const previousStep = useRef(controller.state.step);
  const summary = controller.summary;
  const state = controller.state;
  const cancelScan = controller.cancel;

  useEffect(() => {
    const previous = previousStep.current;
    previousStep.current = state.step;
    if (previous !== 'starting' && state.step === 'starting') {
      recordMobileMetric('my_photos_enrollment_started', 1, { trigger: 'manual', outcome: 'success' });
    } else if (previous !== 'success' && state.step === 'success') {
      recordMobileMetric('my_photos_enrollment_completed', 1, { trigger: 'mutation', outcome: 'success' });
      void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
    } else if (previous !== 'failure' && state.step === 'failure' && (
      state.reason === 'cancelled' || state.reason === 'backgrounded'
    )) {
      recordMobileMetric('my_photos_enrollment_cancelled', 1, {
        trigger: state.reason === 'backgrounded' ? 'background' : 'manual',
        outcome: 'cancelled',
      });
    } else if (previous !== 'failure' && state.step === 'failure' && (
      state.reason === 'camera_denied' || state.reason === 'camera_blocked'
    )) {
      recordMobileMetric('my_photos_permission_denied', 1, { trigger: 'manual', outcome: 'failure' });
    }
  }, [state]);

  const run = async (operation: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await operation();
    } finally {
      setBusy(false);
    }
  };
  const allowCamera = async () => {
    const available = await CameraView.isAvailableAsync().catch(() => false);
    if (!available) {
      controller.cameraUnavailable(false);
      return;
    }
    await run(controller.requestCamera);
  };
  const closeDecision = faceScanCloseDecision(state.step);
  const cancel = useCallback(() => {
    cancelScan();
    if (closeDecision === 'cancel_and_close') router.back();
  }, [cancelScan, closeDecision]);
  useEffect(() => {
    if (closeDecision !== 'cancel_and_stay_for_recovery') return;
    return navigation.addListener('beforeRemove', (event) => {
      event.preventDefault();
      cancelScan();
    });
  }, [cancelScan, closeDecision, navigation]);
  const start = async () => {
    if (!summary.data?.value.capability.provider_ready) {
      recordMobileMetric('my_photos_provider_unavailable', 1, { trigger: 'manual', outcome: 'failure' });
    }
    await run(controller.start);
  };
  const chooseChallenge = (mode: FaceScanChallengeMode) => {
    controller.chooseChallenge(mode);
  };

  const header = (
    <View style={styles.header}>
      <Pressable accessibilityRole="button" accessibilityLabel={messages.myPhotosClose()} onPress={cancel} style={styles.back}>
        <ChevronLeft color={colors.ink} size={26} />
      </Pressable>
      <Text accessibilityRole="header" style={styles.headerTitle}>{messages.myPhotosVerifyFace()}</Text>
    </View>
  );
  const statusScreen = (presentation: Parameters<typeof MyPhotosStatusPanel>[0]['presentation']) => (
    <Screen contentStyle={styles.screen}>
      {header}
      <MyPhotosStatusPanel
        onOpenFaceScan={() => undefined}
        onRefresh={() => void summary.refetch()}
        presentation={presentation}
      />
    </Screen>
  );

  if (!tripId) return statusScreen(myPhotosUnavailablePresentation(messages));
  if (summary.isPending) {
    return (
      <Screen contentStyle={styles.screen}>
        {header}
        <ContentLoading label={messages.loading()} />
      </Screen>
    );
  }
  if (summary.isError || !summary.data) {
    return statusScreen(myPhotosRequestErrorPresentation(summary.error, messages));
  }
  const capabilityBlock = faceScanCapabilityBlock(summary.data.value.capability);
  if (capabilityBlock === 'feature_unavailable') {
    return statusScreen(myPhotosUnavailablePresentation(messages));
  }
  if (capabilityBlock === 'provider_not_configured') {
    return statusScreen({
      tone: 'warning',
      title: messages.myPhotosProviderUnavailable(),
      message: messages.myPhotosProviderNotConfiguredMessage(),
      action: 'none',
      busy: false,
    });
  }
  if (capabilityBlock === 'provider_temporarily_unavailable') {
    return statusScreen({
      tone: 'warning',
      title: messages.myPhotosProviderTemporary(),
      message: messages.myPhotosProviderUnavailable(),
      action: 'refresh',
      busy: false,
    });
  }
  if (state.step === 'running') {
    return (
      <FaceScanRunningSurface
        clientFlow={state.clientFlow}
        onCameraUnavailable={() => controller.cameraUnavailable(true)}
        onCancel={cancel}
        onCompleteDevelopmentSimulation={() => void run(() => controller.simulate('completed'))}
      />
    );
  }
  return (
    <Screen contentStyle={styles.screen}>
      {header}
      <FaceScanStepContent
        busy={busy}
        onAcceptConsent={() => void run(controller.acceptConsent)}
        onAllowCamera={() => void allowCamera()}
        onChallengeMode={chooseChallenge}
        onContinue={state.step === 'preparation' ? controller.continuePreparation : controller.continueExplanation}
        onDone={() => router.back()}
        onOpenSettings={() => void Linking.openSettings()}
        onRetry={controller.retry}
        onStart={() => void start()}
        state={state}
        summary={summary.data.value}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  header: { minHeight: 48, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  back: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { flex: 1, color: colors.ink, fontSize: 20, fontWeight: '900' },
});
