import { z } from 'zod';

import {
  AttendanceRosterPageSchema,
  AttendanceSessionPageSchema,
  CoordinatorPassengerDetailSchema,
} from '@/features/coordinator/api/coordinator-contracts';

const Uuid = z.string().uuid();

export const ManagerPassengerSchema = z
  .object({
    id: Uuid,
    display_name: z.string().min(1).max(255),
    employee_code: z.string().max(120).nullable(),
    visa_status: z.enum(['available', 'not_available']),
    flight_ticket_status: z.enum(['available', 'not_available']),
  })
  .strict();

export const ManagerRosterSchema = z
  .object({
    items: z.array(ManagerPassengerSchema).max(200),
    next_cursor: z.string().max(256).nullable(),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const ManagerPassengerDetailSchema = CoordinatorPassengerDetailSchema;
export const ManagerAttendanceSessionPageSchema = AttendanceSessionPageSchema;
export const ManagerAttendanceRosterPageSchema = AttendanceRosterPageSchema;

export type ManagerPassenger = z.infer<typeof ManagerPassengerSchema>;
export type ManagerPassengerDetail = z.infer<typeof ManagerPassengerDetailSchema>;
export type ManagerRoster = z.infer<typeof ManagerRosterSchema>;
