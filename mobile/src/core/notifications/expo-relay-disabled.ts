import { requireOptionalNativeModule } from 'expo-modules-core';

// Metro substitutes this module for Expo's relay auto-registration side effect.
// It must not install a token listener, fetch a token, or contact the Expo relay.
// Clearing this one native preference retires legacy installs without removing
// authentication, installation identity, permissions, or cached trip content.
const registration = requireOptionalNativeModule<{
  setRegistrationInfoAsync(value: null): Promise<void>;
}>('NotificationsServerRegistrationModule');

export async function setAutoServerRegistrationEnabledAsync(enabled: boolean): Promise<void> {
  if (enabled) throw new Error('Expo push delivery is disabled. Use native FCM or APNs registration.');
  await registration?.setRegistrationInfoAsync(null);
}
