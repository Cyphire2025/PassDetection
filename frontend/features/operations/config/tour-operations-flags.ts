/**
 * Compatibility switch for the retired passenger-by-passenger coordinator UI.
 *
 * Keep the implementation available for an emergency rollback, but do not
 * expose it while coordinators have shared access to the full group roster.
 */
export const PASSENGER_ASSIGNMENT_COMPATIBILITY_UI_ENABLED = false;
