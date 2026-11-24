import { expect, type Page, type Route } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../../features/passports/types/upload-configuration";
import type { FreshDraft } from "../../features/upload/api/fresh-draft.types";

export const freshToken = "synthetic-public-draft-regressions";
export const freshResumeKey = `gc.traveller.draft.v1:${freshToken}`;
export const passportPixel = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPRkAAAAASUVORK5CYII=", "base64");
export const passportFields = {
  given_names: "Asha", surname: "Example", passport_number: "TEST1234", nationality: "IND",
  place_of_issue: "DELHI", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", sex: "F",
};
const base = `/api/v1/public-drafts/${freshToken}`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, json: body, headers: { "cache-control": "private, no-store" } });
export const closedLink = { status: 410, code: "CLIENT_GROUP_CLOSED", message: "This link is closed." };
type Failure = { status: number; code: string; message: string };

/** Synthetic per-member authority. Unmatched API traffic fails closed. */
export async function mockFreshPublicUpload(page: Page, { passport = false } = {}) {
  const drafts = new Map<string, FreshDraft>();
  const starts: string[] = [], reads: string[] = [], completions: string[] = [], unexpected: string[] = [], pageErrors: string[] = [];
  const contacts: Array<{ member: string; kind: "request" | "verify"; body: Record<string, unknown> }> = [];
  const uploads: Array<{ member: string; key: string; revision: number }> = [];
  const completionAttempts: Array<{ member: string; body: Record<string, unknown> }> = [];
  const acceptedUploadKeys = new Set<string>();
  const faults = {
    linkClosed: false, start: undefined as Failure | undefined, read: false, delivery: false,
    rejectProofOnce: false, extractionFailed: false, extractionPending: false, interruptUploadOnce: false,
    resultStatus: "submitted" as "submitted" | "needs_review",
  };
  let challenge = 0;
  const challenges = new Map<string, { id: string; phone: string }>();
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    const member = request.headers()["x-upload-session-id"];
    if (path === `/api/v1/upload-links/token/${freshToken}`) {
      if (faults.linkClosed) return json(route, { detail: closedLink }, closedLink.status);
      return json(route, {
        id: "synthetic-group", name: "Synthetic Singapore Journey", token: freshToken, status: "active",
        travel_date: "2027-12-01", return_date: "2027-12-08", departure_cities: [], custom_questions: [],
        custom_details: [{ id: "reference", label: "Booking reference", enabled: true, required: false }],
        base_city_enabled: true, relation_with_qualifier_enabled: false, qualifier_relation_options: [],
        require_selfie: false, allow_files_from_device: true,
        upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: passport, passport_required: passport,
          passport_upload_pages: ["front"], passport_live_scan: false, required_fields: { base_city: true } },
      });
    }
    if (path === "/api/v1/returning/capabilities") return json(route, { enabled: false, code_label: null });
    if (path.endsWith("/telemetry")) return json(route, {});
    if (path.endsWith("/prepare-file")) {
      expect(member).toBeTruthy();
      return route.fulfill({ contentType: "image/jpeg", body: passportPixel });
    }
    if (!path.startsWith(base) || !member) {
      unexpected.push(`${method} ${path}`);
      return json(route, { detail: "Unexpected API request in isolated synthetic fixture" }, 403);
    }
    if (path === base && method === "POST") {
      starts.push(member);
      if (faults.start) return json(route, { detail: faults.start }, faults.start.status);
      let draft = drafts.get(member);
      if (!draft) {
        draft = { id: `draft-${member}`, revision: 1, status: "active", expires_at: new Date(Date.now() + 86_400_000).toISOString(),
          passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, collection: null,
          verified_phone: null, documents: [], extracted_fields: {}, extraction_status: "none" };
        drafts.set(member, draft);
      } else if (draft.status === "active") {
        // The actual API discards unsubmitted image bytes when a new form visit starts.
        draft.documents = []; draft.extraction_status = "none"; draft.revision++;
      }
      return json(route, draft);
    }
    const draft = drafts.get(member);
    if (!draft) return json(route, { detail: { code: "claim_expired", message: "Your secure session expired." } }, 410);
    if (path === base && method === "GET") {
      reads.push(member);
      if (faults.read) return json(route, { detail: { code: "verification_unavailable", message: "Private draft is temporarily unavailable. Please retry." } }, 503);
      return json(route, draft);
    }
    if (path.endsWith("/activity")) return json(route, { images_present: draft.documents.length > 0, presence_recorded: true, heartbeat_after_seconds: 60 });
    if (path.endsWith("/discard-documents")) {
      if (draft.status === "active") { draft.documents = []; draft.extraction_status = "none"; draft.revision++; }
      return json(route, draft);
    }
    const body = request.headers()["content-type"]?.includes("application/json") ? request.postDataJSON() as Record<string, unknown> : {};
    if (path.endsWith("/contact/request")) {
      contacts.push({ member, kind: "request", body });
      if (faults.delivery) return json(route, { detail: { code: "verification_unavailable", message: "WhatsApp verification is temporarily unavailable. Please retry." } }, 503);
      const next = { id: `challenge-${++challenge}`, phone: String(body.phone_number) };
      challenges.set(member, next);
      return json(route, { challenge_id: next.id, expires_in_seconds: 300, resend_after_seconds: 2 });
    }
    if (path.endsWith("/contact/verify")) {
      contacts.push({ member, kind: "verify", body });
      const current = challenges.get(member);
      expect(body.challenge_id).toBe(current?.id);
      if (body.code !== "123456") return json(route, { detail: { code: "verification_failed", message: "Invalid or expired verification code" } }, 403);
      draft.phone_verification_id = `proof-${member}`;
      draft.phone_verification_expires_at = new Date(Date.now() + 3_600_000).toISOString();
      draft.revision++;
      return json(route, { phone_verification_id: draft.phone_verification_id, phone_number: current!.phone, expires_in_seconds: 3600 });
    }
    if (path.endsWith("/complete")) {
      completionAttempts.push({ member, body });
      expect(body.expected_revision).toBe(draft.revision);
      expect(body.phone_verification_id).toBe(draft.phone_verification_id);
      expect(body.information_confirmed).toBe(true);
      if (faults.rejectProofOnce) {
        faults.rejectProofOnce = false;
        return json(route, { detail: { code: "verification_failed", message: "Verify your WhatsApp number again before submitting." } }, 403);
      }
      if (passport) expect(draft.extraction_status).toBe("succeeded");
      if (!completions.includes(member)) completions.push(member);
      draft.status = "submitted"; draft.source_submission_id = `source-${member}`; draft.result_status = faults.resultStatus;
      return json(route, { source_submission_id: draft.source_submission_id, status: draft.result_status });
    }
    if (path.includes("/documents/")) {
      if (method === "GET") return route.fulfill({ contentType: "image/jpeg", body: passportPixel, headers: { "cache-control": "private, no-store" } });
      const form = await new Request(request.url(), { method: "POST", headers: request.headers(), body: request.postData() }).formData();
      const key = String(form.get("idempotency_key")), revision = Number(form.get("expected_revision"));
      uploads.push({ member, key, revision });
      expect(form.get("file")).toBeTruthy();
      if (!acceptedUploadKeys.has(key)) {
        expect(revision).toBe(draft.revision); acceptedUploadKeys.add(key);
        draft.revision++; draft.documents = [{ id: `front-${member}-${acceptedUploadKeys.size}`, side: "front", state: "ready" }];
        draft.passport_fields = { ...passportFields };
        draft.extraction_status = faults.extractionFailed ? "failed" : faults.extractionPending ? "running" : "succeeded";
      }
      if (faults.interruptUploadOnce) { faults.interruptUploadOnce = false; return route.abort("connectionreset"); }
      return json(route, draft);
    }
    if (path === base && method === "PUT") {
      expect(body.expected_revision).toBe(draft.revision);
      Object.assign(draft, body, { revision: draft.revision + 1 });
      return json(route, draft);
    }
    unexpected.push(`${method} ${path}`);
    return json(route, { detail: "Unexpected private draft request" }, 403);
  });
  return { drafts, starts, reads, completions, contacts, uploads, completionAttempts, acceptedUploadKeys, unexpected, pageErrors, faults };
}
export type FreshFixture = Awaited<ReturnType<typeof mockFreshPublicUpload>>;

export async function enterFresh(page: Page, family = false) {
  await page.goto(`/upload/${freshToken}`);
  await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: family ? "Family" : "Only me", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByLabel("Full name", { exact: true })).toBeVisible();
}
export async function fillFreshDetails(page: Page, { name = "Asha Example", city = "Mumbai", reference = "PRIVATE-BOOKING", family = false, head = false } = {}) {
  await page.getByLabel("Full name", { exact: true }).fill(name);
  await page.getByLabel("Base City", { exact: true }).fill(city);
  await page.getByLabel("Booking reference", { exact: true }).fill(reference);
  if (family) {
    if (!head) await page.getByRole("combobox", { name: "Relationship", exact: true }).selectOption("Spouse");
    await page.getByRole("combobox", { name: "Gender", exact: true }).selectOption(head ? "Female" : "Male");
  }
}
export async function verifyFreshContact(page: Page, email = "asha@example.test", phone = "9900001234") {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("WhatsApp number", { exact: true }).fill(phone);
  await page.getByRole("button", { name: /^(Verify WhatsApp number|Resend code)$/ }).click();
  await page.getByLabel("Verification code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Confirm code", exact: true }).click();
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
}
export async function uploadFreshPassport(page: Page, name = "synthetic-passport.jpg") {
  await page.getByLabel("Upload personal details page").setInputFiles({ name, mimeType: "image/jpeg", buffer: passportPixel });
}
export async function readFreshResume(page: Page) {
  return page.evaluate(key => JSON.parse(localStorage.getItem(key)!), freshResumeKey);
}
export async function seedFreshResume(page: Page) {
  const record = { version: 1, expiresAt: Date.now() + 86_400_000, mode: "new", submissionKey: "resume-navigation-key",
    fresh: { mode: "single", familyGroupId: "synthetic-family", active: 0, members: [{ sessionId: "private-resume-session", submissionKey: "stable-final-key", completed: false }] } };
  await page.addInitScript(({ key, value }) => localStorage.setItem(key, JSON.stringify(value)), { key: freshResumeKey, value: record });
  return record;
}
export async function resumeFresh(page: Page) {
  await page.goto(`/upload/${freshToken}`);
  await page.getByRole("button", { name: /Continue from where you left/ }).click();
}
export function expectFreshFixtureClean(state: FreshFixture) {
  expect(state.unexpected).toEqual([]); expect(state.pageErrors).toEqual([]);
}
