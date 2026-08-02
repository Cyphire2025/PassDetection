import { Text, StyleSheet } from 'react-native';

import { ApiError } from '@/core/api/client';
import { colors } from '@/design/theme';

export function authErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return 'Please wait before trying again.';
    if (error.status === 401) return 'Those details could not be verified.';
    return error.message;
  }
  return 'Something went wrong. Check your connection and try again.';
}

export function AuthError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <Text accessibilityRole="alert" style={styles.error}>
      {message}
    </Text>
  );
}

const styles = StyleSheet.create({ error: { color: colors.danger, fontSize: 14, lineHeight: 20 } });
