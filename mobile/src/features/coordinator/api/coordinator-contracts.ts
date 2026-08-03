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

const CoordinatorDocumentStatusSchema = z.enum(['available', 'not_available']);

export const CoordinatorOperationalDetailSchema = z
  .object({
    key: z.string().min(1).max(160),
    label: z.string().min(1).max(120),
    value: z.string().min(1).max(2_048),
    source: z.enum(['imported', 'custom_question', 'custom_detail']),
  })
  .strict();

export const CoordinatorPassengerDetailSchema = z
  .object({
    id: Uuid,
    display_name: z.string().min(1).max(255),
    employee_code: z.string().max(120).nullable(),
    employee_type: z.string().max(120).nullable(),
    staff_code: z.string().max(120).nullable(),
    base_city: z.string().max(120).nullable(),
    agency_dealership_name: z.string().max(200).nullable(),
    zone_name: z.string().max(120).nullable(),
    attendance_status: z.enum(['not_marked', 'present', 'missing', 'excused']),
    has_alert: z.boolean(),
    phone_number: z.string().max(32).nullable(),
    email: z.string().max(255).nullable(),
    departure_city: z.string().max(120).nullable(),
    nearest_domestic_airport: z.string().max(120).nullable(),
    designation: z.string().max(160).nullable(),
    department: z.string().max(160).nullable(),
    gender: z.string().max(40).nullable(),
    date_of_birth: z.string().date().nullable(),
    nationality: z.string().max(80).nullable(),
    passport_surname: z.string().max(160).nullable(),
    passport_given_names: z.string().max(255).nullable(),
    passport_place_of_issue: z.string().max(160).nullable(),
    passport_issuing_country: z.string().max(120).nullable(),
    passport_date_of_issue: z.string().date().nullable(),
    passport_date_of_expiry: z.string().date().nullable(),
    hotel_name: z.string().max(255).nullable(),
    room_number: z.string().max(80).nullable(),
    roommate_summary: z.string().max(500).nullable(),
    meal_preference: z.string().max(255).nullable(),
    family_relation: z.string().max(80).nullable(),
    family_head_name: z.string().max(255).nullable(),
    family_head_phone: z.string().max(32).nullable(),
    family_head_email: z.string().max(255).nullable(),
    qualifier_relation: z.string().max(80).nullable(),
    emergency_contact_name: z.string().max(255).nullable(),
    emergency_contact_phone: z.string().max(64).nullable(),
    emergency_contact_relation: z.string().max(120).nullable(),
    operational_remarks: z.string().max(2_048).nullable(),
    submission_mode: z.enum(['single', 'family']),
    submission_status: z.string().min(1).max(40),
    passport_status: CoordinatorDocumentStatusSchema,
    visa_status: CoordinatorDocumentStatusSchema,
    flight_ticket_status: CoordinatorDocumentStatusSchema,
    insurance_status: CoordinatorDocumentStatusSchema,
    hotel_voucher_status: CoordinatorDocumentStatusSchema,
    other_document_status: CoordinatorDocumentStatusSchema,
    additional_details: z.array(CoordinatorOperationalDetailSchema).max(300),
    updated_at: IsoDateTime,
  })
  .strict();

export type CoordinatorPassengerDetail = z.infer<typeof CoordinatorPassengerDetailSchema>;

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
