import type { MobileRole } from '@/core/auth/types';

export type Trip = {
  id: string;
  name: string;
  destination: string | null;
  travelDate: string | null;
  returnDate: string | null;
  role: MobileRole;
  accessGeneration: number;
  accessExpiresAt: string | null;
  itineraryVersion: number;
  commonDocumentVersion: number;
  announcementVersion: number;
  updatedAt: string;
};
