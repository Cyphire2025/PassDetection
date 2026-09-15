import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import React from 'react';

import OtpScreen from '@/app/(auth)/otp';
import { activateSession } from '@/core/auth/session-service';
import { verifyOtp } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';

jest.mock('expo-router', () => ({ router: { replace: jest.fn(), push: jest.fn() }, Redirect: () => null }));
jest.mock('@/core/auth/session-service', () => ({ activateSession: jest.fn() }));
jest.mock('@/features/auth/api/auth-api', () => ({ requestOtp: jest.fn(), verifyOtp: jest.fn() }));
jest.mock('@/features/auth/ui/auth-shell', () => ({
  AuthShell: ({ title, description, children }: { title: string; description: string; children: React.ReactNode }) => {
    const { View, Text } = jest.requireActual('react-native');
    return <View><Text>{title}</Text><Text>{description}</Text>{children}</View>;
  },
}));
jest.mock('@/design/components/primary-button', () => ({
  PrimaryButton: ({ label, onPress }: { label: string; onPress: () => void }) => {
    const { Pressable, Text } = jest.requireActual('react-native');
    return <Pressable onPress={onPress}><Text>{label}</Text></Pressable>;
  },
}));
jest.mock('@/features/auth/ui/otp-code-input', () => ({
  OtpCodeInput: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => {
    const { TextInput } = jest.requireActual('react-native');
    return <TextInput testID="otp-test-input" value={value} onChangeText={onChange} />;
  },
}));
jest.mock('@/features/auth/ui/countdown-progress', () => ({ CountdownProgress: () => null }));

beforeEach(() => {
  jest.clearAllMocks();
  const flow = useAuthFlowStore.getState();
  flow.reset();
  flow.setPhoneNumber('+919876543210');
  flow.setChallenge({ challengeId: '11111111-1111-4111-8111-111111111111', expiresInSeconds: 300, resendAfterSeconds: 60 });
});

it.each([
  ['trip_not_active', 'Your trip is not active in GC App yet.'],
  ['trip_starts_later', 'Your trip access starts later.'],
  ['trip_access_ended', 'Your trip access has ended.'],
] as const)('shows ownership-proven %s guidance without activating a session', async (status, title) => {
  jest.mocked(verifyOtp).mockResolvedValue({ status, claims: [], tokens: null });
  await render(<OtpScreen />);
  expect(screen.queryByText(title)).toBeNull();
  await fireEvent.changeText(screen.getByTestId('otp-test-input'), '123456');
  await fireEvent.press(screen.getByText('Verify'));
  await waitFor(() => expect(screen.getByText(title)).toBeTruthy());
  expect(verifyOtp).toHaveBeenCalledWith('11111111-1111-4111-8111-111111111111', '123456', '+919876543210');
  expect(activateSession).not.toHaveBeenCalled();
  expect(screen.queryByTestId('otp-test-input')).toBeNull();
  await fireEvent.press(screen.getByText('Back to sign in'));
  expect(useAuthFlowStore.getState().challengeId).toBeNull();
});

it('keeps inactive-trip information hidden when OTP verification fails', async () => {
  jest.mocked(verifyOtp).mockRejectedValue(new Error('Verification unavailable'));
  await render(<OtpScreen />);
  await fireEvent.changeText(screen.getByTestId('otp-test-input'), '123456');
  await fireEvent.press(screen.getByText('Verify'));
  await waitFor(() => expect(verifyOtp).toHaveBeenCalledTimes(1));
  expect(screen.queryByText('Your trip is not active in GC App yet.')).toBeNull();
  expect(activateSession).not.toHaveBeenCalled();
});
