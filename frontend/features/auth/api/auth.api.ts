/**
 * Auth API — Login & Token Operations
 * =====================================
 * Encapsulates all auth HTTP calls.
 * Components and hooks never call axios directly.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { AuthSession, AuthTokens, User } from "@/types";
import type { LoginFormData } from "../schemas/auth.schemas";

export const authApi = {
  /**
   * Exchange credentials for access + refresh tokens.
   * Backend uses OAuth2 password flow (application/x-www-form-urlencoded).
   */
  login: async (data: LoginFormData): Promise<AuthSession> => {
    // OAuth2 password flow requires form-encoded body
    const formData = new URLSearchParams({
      username: data.email,
      password: data.password,
    });
    const response = await apiClient.post<{
      user: User;
      access_token: string;
      refresh_token: string;
      token_type: "bearer";
    }>(
      API_ENDPOINTS.auth.login,
      formData,
      { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
    );
    const { user, access_token, refresh_token, token_type } = response.data;
    return {
      user,
      tokens: {
        access_token,
        refresh_token,
        token_type,
      },
    };
  },


  /**
   * Fetch the currently authenticated user's profile.
   */
  getMe: async (): Promise<User> => {
    const response = await apiClient.get<User>(API_ENDPOINTS.auth.me);
    return response.data;
  },

  /**
   * Refresh the access token using the refresh token.
   */
  refreshToken: async (refreshToken: string): Promise<AuthTokens> => {
    const response = await apiClient.post<AuthTokens>(
      API_ENDPOINTS.auth.refresh,
      { refresh_token: refreshToken }
    );
    return response.data;
  },

  logout: async (refreshToken: string): Promise<void> => {
    await apiClient.post(API_ENDPOINTS.auth.logout, { refresh_token: refreshToken });
  },
};

