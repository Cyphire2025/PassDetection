import { useCallback, useEffect, useState } from 'react';
import { AppState, Linking, Platform, StyleSheet, Text } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { principalAccountNamespace } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { usePushRegistrationState } from '@/core/notifications/notification-registration-state';
import { registerPushDevice } from '@/core/notifications/notification-service';
import { readNotificationSettings, type NotificationSettings } from '@/core/notifications/notification-settings';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

const REGISTRATION_MESSAGES = {
  registering: 'Checking this device’s notification registration…',
  registered: 'This device is registered for trip alerts. Delivery also depends on your connection and phone settings.',
  permission_denied: 'Phone notifications are not allowed. Enable them in phone settings, then retry registration.',
  unsupported_device: 'Phone alerts require a physical device.',
  unsupported_platform: 'Phone alerts are available on Android only in this version. Read Updates in the app and contact your travel team for urgent changes.',
  offline: 'Connect to the internet to register this device for alerts.',
  build_unconfigured: 'This app build is missing notification configuration. Contact your travel team for an updated build.',
  token_unavailable: 'The phone notification service is temporarily unavailable. Check your connection and retry.',
  registration_failed: 'Notification registration could not be confirmed with the server. Check your connection and retry.',
};

export function NotificationSettingsCard() {
  const session = useSessionStore((state) => state.session);
  const scope = session ? `${principalAccountNamespace(session.principal)}.${session.sessionId}` : null;
  const status = usePushRegistrationState((state) => state.scope === scope ? state.status : null);
  const [settings, setSettings] = useState<NotificationSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);
  const demo = isDemoMode();
  const supportedPlatform = Platform.OS === 'android';

  const refreshSettings = useCallback(() => readNotificationSettings()
    .then((next) => { setSettings(next); setError(null); })
    .catch(() => {
      setError('Could not read phone notification settings. Open phone settings to check them.');
    }), []);
  useEffect(() => {
    if (demo) return;
    void refreshSettings();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void refreshSettings();
    });
    return () => subscription.remove();
  }, [demo, refreshSettings]);

  const retry = async () => {
    setRetrying(true);
    try {
      await registerPushDevice(undefined, { force: true });
    } catch {
      // Registration exposes only a safe, account-scoped explanation above.
    } finally {
      await refreshSettings();
      setRetrying(false);
    }
  };
  const message = demo ? 'Phone alerts are unavailable in the demo.'
    : !supportedPlatform ? REGISTRATION_MESSAGES.unsupported_platform
      : settings && !settings.physicalDevice ? REGISTRATION_MESSAGES.unsupported_device
      : settings && !settings.permissionGranted ? REGISTRATION_MESSAGES.permission_denied
        : settings?.channelBlocked ? 'Trip updates are blocked in Android notification settings. Enable the Trip updates channel, then retry.'
          : session?.networkMode !== 'online' ? REGISTRATION_MESSAGES.offline
            : status ? REGISTRATION_MESSAGES[status]
              : 'Notification registration has not been confirmed in this session. Retry to check this device.';

  return (
    <GlassCard style={styles.card}>
      <Text accessibilityRole="header" style={styles.title}>Phone notifications</Text>
      <Text accessibilityLiveRegion="polite" style={styles.description}>{message}</Text>
      {error ? <Text accessibilityRole="alert" style={styles.description}>{error}</Text> : null}
      <PrimaryButton label="Retry notification registration" tone="secondary" loading={retrying}
        disabled={demo || !supportedPlatform || !session || session.networkMode !== 'online'} onPress={() => void retry()} />
      <PrimaryButton label="Open phone notification settings" tone="secondary" onPress={() => {
        void Linking.openSettings().catch(() => setError('Open this app’s notification settings from your phone Settings app.'));
      }} />
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  card: { gap: spacing.md },
  title: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  description: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
