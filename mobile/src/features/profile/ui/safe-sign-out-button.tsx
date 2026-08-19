import { StyleSheet, Text, View } from 'react-native';

import { useSafeSignOut } from '@/core/auth/use-safe-sign-out';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';

export function SafeSignOutButton({
  label = 'Sign out',
  testID = 'safe-sign-out',
}: {
  label?: string;
  testID?: string;
}) {
  const signOut = useSafeSignOut();
  return (
    <View style={styles.container}>
      {signOut.errorMessage ? (
        <Text accessibilityRole="alert" style={styles.error}>{signOut.errorMessage}</Text>
      ) : null}
      <PrimaryButton
        testID={testID}
        label={signOut.errorMessage ? 'Retry secure cleanup' : label}
        loading={signOut.isSigningOut}
        tone="danger"
        onPress={() => void (signOut.errorMessage ? signOut.retryCleanup() : signOut.signOut())}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: spacing.sm },
  error: { color: colors.danger, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
