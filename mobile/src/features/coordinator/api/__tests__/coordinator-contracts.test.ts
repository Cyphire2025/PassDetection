import { CoordinatorPassengerDetailSchema } from '../coordinator-contracts';

const safeDetail = {
  id: '8cb51225-5543-4204-bbea-06bebffc35ad',
  display_name: 'Passenger Example',
  employee_code: 'EMP-1',
  employee_type: 'Employee',
  staff_code: 'STAFF-1',
  base_city: 'Delhi',
  agency_dealership_name: 'Example Company',
  zone_name: 'North',
  attendance_status: 'not_marked',
  has_alert: false,
  phone_number: '+919999999999',
  email: 'passenger@example.com',
  departure_city: 'Delhi',
  nearest_domestic_airport: 'DEL',
  designation: 'Manager',
  department: 'Operations',
  gender: 'Female',
  date_of_birth: '1990-04-12',
  nationality: 'Indian',
  passport_surname: 'Example',
  passport_given_names: 'Passenger',
  passport_place_of_issue: 'Delhi',
  passport_issuing_country: 'India',
  passport_date_of_issue: '2024-01-10',
  passport_date_of_expiry: '2034-01-09',
  hotel_name: 'Example Hotel',
  room_number: '402',
  roommate_summary: 'Passenger Two',
  meal_preference: 'Vegetarian',
  family_relation: null,
  family_head_name: null,
  family_head_phone: null,
  family_head_email: null,
  qualifier_relation: 'Self',
  emergency_contact_name: 'Emergency Contact',
  emergency_contact_phone: '+919888888888',
  emergency_contact_relation: 'Sibling',
  operational_remarks: 'Wheelchair assistance at departure.',
  submission_mode: 'single',
  submission_status: 'staff_approved',
  passport_status: 'available',
  visa_status: 'not_available',
  flight_ticket_status: 'available',
  insurance_status: 'not_available',
  hotel_voucher_status: 'available',
  other_document_status: 'not_available',
  additional_details: [
    {
      key: 'custom_detail:meal_service',
      label: 'Meal service',
      value: 'Jain meal',
      source: 'custom_detail',
    },
  ],
  updated_at: '2026-08-03T09:00:00+00:00',
} as const;

test('accepts the explicit coordinator passenger detail projection', () => {
  expect(CoordinatorPassengerDetailSchema.parse(safeDetail)).toEqual(safeDetail);
});

test.each([
  ['passport_number', 'P1234567'],
  ['mrz', 'P<IND...'],
  ['passport_image_url', 'https://storage.example/passport.jpg'],
  ['ai_confidence', 0.99],
  ['internal_notes', 'private'],
])('rejects non-allowlisted sensitive coordinator detail field %s', (key, value) => {
  expect(CoordinatorPassengerDetailSchema.safeParse({ ...safeDetail, [key]: value }).success).toBe(false);
});
