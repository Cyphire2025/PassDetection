import { MOBILE_GROUP_PASSENGER_CAPACITY } from './full-roster-sync';

/** Mirrors the backend mobile manifest contract for one group's activity history. */
export const MOBILE_ATTENDANCE_SESSION_CAPACITY = 10_000;

/** Counted and missing views are both subsets of the bounded group roster. */
export const MOBILE_ATTENDANCE_ROSTER_CAPACITY = MOBILE_GROUP_PASSENGER_CAPACITY;
