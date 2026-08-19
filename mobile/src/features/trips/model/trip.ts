import type { MobileRole } from '@/core/auth/types';
import type { IanaTimeZone } from '@/core/localization/time-zone';

export type Trip = {
  id: string;
  name: string;
  destination: string | null;
  travelDate: string | null;
  returnDate: string | null;
  timeZone: IanaTimeZone;
  role: MobileRole;
  accessGeneration: number;
  accessExpiresAt: string | null;
  itineraryVersion: number;
  commonDocumentVersion: number;
  announcementVersion: number;
  updatedAt: string;
};
