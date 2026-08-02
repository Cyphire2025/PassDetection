import * as Application from 'expo-application';
import * as Device from 'expo-device';
import { Platform } from 'react-native';

import {
  MobileDeviceSchema,
  OtpRequestResponseSchema,
  OtpVerifyResponseSchema,
  PrincipalSchema,
  TokenResponseSchema,
  type MobileDeviceInput,
} from '@/core/api/contracts';
import { apiRequest } from '@/core/api/client';
import { getInstallationId } from '@/core/storage/secure-store';

export async function mobileDevice(): Promise<MobileDeviceInput> {
  if (Platform.OS !== 'android' && Platform.OS !== 'ios') {
    throw new Error('Group Companion authentication requires Android or iOS.');
  }

  return MobileDeviceSchema.parse({
    installation_id: await getInstallationId(),
    platform: Platform.OS,
    app_version: Application.nativeApplicationVersion ?? 'development',
    device_name: Device.modelName ?? null,
  });
}

export function requestOtp(phoneNumber: string) {
  return apiRequest('/mobile/auth/otp/request', {
    method: 'POST',
    authenticated: false,
    schema: OtpRequestResponseSchema,
    body: { phone_number: phoneNumber },
  });
}

export async function verifyOtp(challengeId: string, code: string) {
  return apiRequest('/mobile/auth/otp/verify', {
    method: 'POST',
    authenticated: false,
    schema: OtpVerifyResponseSchema,
    body: {
      challenge_id: challengeId,
      code,
      device: await mobileDevice(),
    },
  });
}

export async function verifyPassengerClaim(input: {
  challengeId: string;
  claimId?: string;
  verificationValue?: string;
}) {
  return apiRequest('/mobile/auth/claim/verify', {
    method: 'POST',
    authenticated: false,
    schema: OtpVerifyResponseSchema,
    body: {
      challenge_id: input.challengeId,
      ...(input.claimId ? { claim_id: input.claimId } : {}),
      ...(input.verificationValue ? { verification_value: input.verificationValue } : {}),
      device: await mobileDevice(),
    },
  });
}

export async function credentialLogin(email: string, password: string) {
  return apiRequest('/mobile/auth/login', {
    method: 'POST',
    authenticated: false,
    schema: TokenResponseSchema,
    body: { email, password, device: await mobileDevice() },
  });
}

export async function activateInvitation(activationToken: string, newPassword: string) {
  return apiRequest('/mobile/auth/activate', {
    method: 'POST',
    authenticated: false,
    retryAuthentication: false,
    schema: TokenResponseSchema,
    body: {
      activation_token: activationToken,
      new_password: newPassword,
      device: await mobileDevice(),
    },
  });
}

export function refreshSession(refreshToken: string) {
  return apiRequest('/mobile/auth/refresh', {
    method: 'POST',
    authenticated: false,
    retryAuthentication: false,
    schema: TokenResponseSchema,
    body: { refresh_token: refreshToken },
  });
}

export async function changeForcedPassword(currentPassword: string, newPassword: string) {
  return apiRequest('/mobile/auth/password/change', {
    method: 'POST',
    schema: TokenResponseSchema,
    body: {
      current_password: currentPassword,
      new_password: newPassword,
      device: await mobileDevice(),
    },
  });
}

export function fetchMe() {
  return apiRequest('/mobile/me', { schema: PrincipalSchema });
}

export async function logoutRemote(refreshToken: string | null): Promise<void> {
  const responseSchema = {
    safeParse: (value: unknown) => ({ success: value === null, data: null }),
  } as never;
  await apiRequest('/mobile/auth/logout', {
    method: 'POST',
    schema: responseSchema,
    body: refreshToken ? { refresh_token: refreshToken } : {},
  });
}
