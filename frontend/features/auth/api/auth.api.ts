/**
 * Auth API — Login & Token Operations
 * =====================================
 * Encapsulates all auth HTTP calls.
 * Components and hooks never call axios directly.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { AuthOutcome, AuthSession, IdentityActionOutcome, MFAEnrollmentSession, User } from "@/types";
import type { LoginFormData } from "../schemas/auth.schemas";

export const authApi = {
  /**
   * Exchange credentials for an httpOnly cookie session.
   */
  login: async (data: LoginFormData): Promise<AuthOutcome> => {
    // OAuth2 password flow requires form-encoded body
    const formData = new URLSearchParams({
      username: data.email,
      password: data.password,
    });
    const response = await apiClient.post<AuthOutcome>(
      API_ENDPOINTS.auth.login,
      formData,
      { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
    );
    return response.data;
  },

  verifyMfa: async (challengeToken: string, code: string): Promise<MFAEnrollmentSession> => {
    const response = await apiClient.post<MFAEnrollmentSession>(API_ENDPOINTS.auth.mfaVerify, {
      challenge_token: challengeToken,
      code,
    });
    return response.data;
  },

  activate: async (token: string, newPassword: string): Promise<IdentityActionOutcome> => {
    const response = await apiClient.post<IdentityActionOutcome>(API_ENDPOINTS.auth.activate, {
      token,
      new_password: newPassword,
    });
    return response.data;
  },

  requestPasswordRecovery: async (email: string): Promise<{ message: string; development_recovery_token: string | null }> => {
    const response = await apiClient.post<{ message: string; development_recovery_token: string | null }>(
      API_ENDPOINTS.auth.passwordRecoveryRequest,
      { email },
    );
    return response.data;
  },

  completePasswordRecovery: async (token: string, newPassword: string): Promise<IdentityActionOutcome> => {
    const response = await apiClient.post<IdentityActionOutcome>(API_ENDPOINTS.auth.passwordRecoveryComplete, {
      token,
      new_password: newPassword,
    });
    return response.data;
  },

  changePassword: async (currentPassword: string, newPassword: string): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.auth.passwordChange, {
      current_password: currentPassword,
      new_password: newPassword,
    });
  },

  stepUp: async (code: string): Promise<AuthSession> => {
    const response = await apiClient.post<AuthSession>(API_ENDPOINTS.auth.mfaStepUp, { code });
    return response.data;
  },

  regenerateMfaRecoveryCodes: async (): Promise<string[]> => {
    const response = await apiClient.post<{ recovery_codes: string[] }>(API_ENDPOINTS.auth.mfaRecoveryCodes);
    return response.data.recovery_codes;
  },


  /**
   * Fetch the currently authenticated user's profile.
   */
  getMe: async (signal?: AbortSignal): Promise<User> => {
    const response = await apiClient.get<User>(API_ENDPOINTS.auth.me, { signal });
    return response.data;
  },

  /**
   * Refresh the access token using the refresh token.
   */
  refreshToken: async (): Promise<AuthSession> => {
    const response = await apiClient.post<AuthSession>(API_ENDPOINTS.auth.refresh);
    return response.data;
  },

  logout: async (): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.auth.logout);
  },

  logoutAll: async (): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.auth.logoutAll);
  },

};
