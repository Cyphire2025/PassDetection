import { z } from 'zod';

const Uuid = z.string().uuid();
const IsoDateTime = z.string().datetime({ offset: true });

export const CoordinatorPassengerSchema = z
  .object({
    id: Uuid,
    display_name: z.string().min(1).max(255),
    employee_code: z.string().max(120).nullable(),
    attendance_status: z.enum(['not_marked', 'present', 'missing', 'excused']),
    room_number: z.string().max(80).nullable(),
    meal_preference: z.string().max(255).nullable(),
    has_alert: z.boolean(),
  })
  .strict();

export const CoordinatorRosterSchema = z
  .object({
    items: z.array(CoordinatorPassengerSchema).max(200),
    next_cursor: z.string().max(256).nullable(),
    total: z.number().int().nonnegative(),
  })
  .strict();

export type CoordinatorPassenger = z.infer<typeof CoordinatorPassengerSchema>;

export const AttendanceActionResultSchema = z
  .object({
    client_event_id: Uuid,
    status: z.enum(['accepted', 'already_applied', 'rejected', 'refresh_required']),
    server_version: z.number().int().nonnegative().nullable(),
    reason_code: z.string().max(100).nullable(),
  })
  .strict();

export const AttendanceBatchResponseSchema = z
  .object({ results: z.array(AttendanceActionResultSchema).min(1).max(100) })
  .strict();

export const AttendanceSummarySchema = z
  .object({
    trip_id: Uuid,
    total: z.number().int().nonnegative(),
    present: z.number().int().nonnegative(),
    missing: z.number().int().nonnegative(),
    excused: z.number().int().nonnegative(),
    not_marked: z.number().int().nonnegative(),
    version: z.number().int().nonnegative(),
    updated_at: IsoDateTime,
  })
  .strict();

export const IncidentActionResponseSchema = z
  .object({
    client_event_id: Uuid,
    status: z.enum(['accepted', 'already_applied', 'rejected']),
    incident_id: Uuid.nullable(),
    reason_code: z.string().max(100).nullable(),
  })
  .strict();

export const AttendanceSessionSchema = z
  .object({
    id: Uuid,
    name: z.string().min(2).max(160),
    status: z.enum(['draft', 'active', 'completed', 'cancelled']),
    scanned_count: z.number().int().nonnegative(),
    assigned_count: z.number().int().nonnegative(),
    started_at: IsoDateTime.nullable(),
    completed_at: IsoDateTime.nullable(),
  })
  .strict();

export type AttendanceSession = z.infer<typeof AttendanceSessionSchema>;

export const AttendanceSessionPageSchema = z
  .object({
    items: z.array(AttendanceSessionSchema).max(100),
    next_cursor: z.string().max(256).nullable(),
  })
  .strict();

export const MissingPassengerSchema = z
  .object({
    id: Uuid,
    display_name: z.string().min(1).max(255),
  })
  .strict();

export const AttendanceSessionDetailSchema = z
  .object({
    session: AttendanceSessionSchema,
    missing: z.array(MissingPassengerSchema).max(200),
    next_cursor: z.string().max(256).nullable(),
  })
  .strict();

export type MissingPassenger = z.infer<typeof MissingPassengerSchema>;
