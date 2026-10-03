import { expect, type Page, type Route } from "@playwright/test";
import type { TrackerKind, TrackerPassenger } from "../../features/travel-tracker/types";

export const trackerGroupId = "00000000-0000-4000-8000-000000000101";
const user = {
  id: "tracker-admin", email: "tracker@example.test", full_name: "Tracker Admin",
  role: "agency_admin", agency_id: "tracker-agency", is_active: true,
  last_login_at: null, created_at: "2026-10-04T00:00:00Z", updated_at: "2026-10-04T00:00:00Z",
};
const respond = (route: Route, body: unknown, status = 200) => route.fulfill({
  status, contentType: "application/json", body: JSON.stringify(body),
});

/** Entirely synthetic API. Every request is intercepted before any upstream rewrite. */
export async function mockTravelTracker(page: Page, size = 137, role: "agency_admin" | "super_admin" = "agency_admin") {
  const activeUser = role === "super_admin"
    ? { ...user, role, agency_id: null, capabilities: ["mcp.manage", "gc_app.manage"] }
    : user;
  const passengers: TrackerPassenger[] = Array.from({ length: size }, (_, index) => ({
    id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
    full_name: index === 0 ? "Asha Patel" : index === 1 ? "Imported Traveller" : `Passenger ${String(index + 1).padStart(3, "0")}`,
    given_name: index === 0 ? "Asha" : "Passenger", surname: index === 0 ? "Patel" : String(index + 1),
    passport_number: `P${String(index + 1).padStart(7, "0")}`, nationality: "IND", gender: "F",
    date_of_birth: "1991-03-01", date_of_expiry: "2031-05-01", email: `person${index}@example.test`,
    phone: `919876${String(index).padStart(6, "0")}`, departure_city: "Mumbai",
    submission_status: index === 1 ? "pending" : "approved",
    visa_applied: false, flight_booked: false, visa_updated_at: null, flight_updated_at: null,
  }));
  const markRequests: unknown[] = [];
  const marked = (person: TrackerPassenger, track: TrackerKind) => track === "visa" ? person.visa_applied : person.flight_booked;
  const group = () => ({
    id: trackerGroupId, name: "Singapore October", destination: "Singapore", status: "active",
    travel_date: "2026-10-20", return_date: "2026-10-25", total: passengers.length,
    visa_marked: passengers.filter((person) => person.visa_applied).length,
    flight_marked: passengers.filter((person) => person.flight_booked).length,
  });
  const counts = (track: TrackerKind) => ({ total: size, marked: passengers.filter((person) => marked(person, track)).length, pending: passengers.filter((person) => !marked(person, track)).length });
  const filter = (track: TrackerKind, status: string, search: string | null = "") => passengers.filter((person) => (
    (status === "all" || marked(person, track) === (status === "marked"))
    && `${person.full_name} ${person.passport_number} ${person.email} ${person.phone}`.toLowerCase().includes((search ?? "").toLowerCase())
  ));
  await page.context().addCookies([{ name: "access_token", value: "synthetic-session", domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" }]);
  await page.addInitScript(() => Object.defineProperty(window, "showSaveFilePicker", { value: undefined, configurable: true }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/me") return respond(route, activeUser);
    if (path === "/api/v1/auth/refresh") return respond(route, { status: "authenticated", user: activeUser, token_type: "bearer", access_token_expires_at: new Date(Date.now() + 30 * 60_000).toISOString() });
    if (path === "/api/v1/notifications/feed") return respond(route, { items: [], unread_count: 0, next_cursor: null });
    if (path === "/api/v1/travel-tracker/groups") {
      const matches = group().name.toLowerCase().includes((url.searchParams.get("search") ?? "").toLowerCase());
      return respond(route, { groups: matches ? [group()] : [], total: matches ? 1 : 0, page: 1, page_size: 24 });
    }
    const base = `/api/v1/travel-tracker/groups/${trackerGroupId}`;
    if (path === base) {
      const track = (url.searchParams.get("track") ?? "visa") as TrackerKind;
      const rows = filter(track, url.searchParams.get("status") ?? "all", url.searchParams.get("search") ?? "");
      const current = Number(url.searchParams.get("page") ?? 1);
      const pageSize = Number(url.searchParams.get("page_size") ?? 50);
      return respond(route, { group: group(), counts: counts(track), passengers: rows.slice((current - 1) * pageSize, current * pageSize), total: rows.length, page: current, page_size: pageSize });
    }
    if (path === `${base}/marks`) {
      const body = request.postDataJSON();
      markRequests.push(body);
      const rows = body.passenger_ids
        ? passengers.filter((person) => body.passenger_ids.includes(person.id))
        : filter(body.track, body.selection.status, body.selection.search);
      if (body.selection) expect(rows.length).toBe(body.expected_count);
      let changed = 0;
      rows.forEach((person) => {
        if (marked(person, body.track) !== body.marked) changed++;
        if (body.track === "visa") person.visa_applied = body.marked;
        else person.flight_booked = body.marked;
      });
      return respond(route, { updated_count: changed, unchanged_count: rows.length - changed, passenger_ids: rows.map((person) => person.id), counts: counts(body.track) });
    }
    if (path === `${base}/import/preview`) {
      const fileBody = request.postDataBuffer()!.toString();
      expect(fileBody).toContain('name="file"');
      return respond(route, {
        track: fileBody.includes("flight") ? "flight" : "visa", marked: true,
        total_rows: 3, matched_count: 1, ambiguous_count: 1, unmatched_count: 1, duplicate_count: 0,
        passenger_ids: [passengers[0].id], rows: [
          { row_number: 2, name: "Asha Patel", passport_number: null, passenger_id: passengers[0].id, passenger_name: "Asha Patel", status: "matched", reason: "Unique exact name" },
          { row_number: 3, name: "Duplicate Name", passport_number: null, passenger_id: null, passenger_name: null, status: "ambiguous", reason: "Two passengers share this name. Add a passport number." },
          { row_number: 4, name: "Missing Person", passport_number: null, passenger_id: null, passenger_name: null, status: "unmatched", reason: "No match in this group" },
        ],
      });
    }
    if (path === `${base}/export`) {
      return route.fulfill({ contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers: { "content-disposition": 'attachment; filename="tracker.xlsx"' }, body: Buffer.from("synthetic-download") });
    }
    return respond(route, []);
  });
  return { passengers, markRequests };
}
