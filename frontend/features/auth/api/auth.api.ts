/**
 * Auth API — Login & Token Operations
 * =====================================
 * Encapsulates all auth HTTP calls.
 * Components and hooks never call axios directly.
 */

import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { AuthSession, User } from "@/types";
import type { LoginFormData } from "../schemas/auth.schemas";

export const authApi = {
  /**
   * Exchange credentials for an httpOnly cookie session.
   */
  login: async (data: LoginFormData): Promise<AuthSession> => {
    // OAuth2 password flow requires form-encoded body
    const formData = new URLSearchParams({
      username: data.email,
      password: data.password,
    });
    const response = await apiClient.post<{
      user: User;
      token_type: "bearer";
      access_token_expires_at: string | null;
    }>(
      API_ENDPOINTS.auth.login,
      formData,
      { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
    );
    return response.data;
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
