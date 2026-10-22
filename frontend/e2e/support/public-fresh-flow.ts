import { expect, type Page, type Route } from "@playwright/test";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../../features/passports/types/upload-configuration";
import type { FreshDraft } from "../../features/upload/api/fresh-draft.api";

export const freshPixel = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jPRkAAAAASUVORK5CYII=", "base64");
const freshPreparedJpeg = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAv/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/ALUAYP/Z", "base64");
export const freshFields = { given_names: "Asha", surname: "Example", passport_number: "TEST1234", nationality: "IND", place_of_issue: "DELHI", date_of_birth: "1990-01-01", date_of_issue: "2022-01-01", date_of_expiry: "2032-01-01", sex: "F" };
export const freshStorageKey = (token: string) => `gc.traveller.draft.v1:${token}`;
const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

interface FixtureOptions {
  group?: Record<string, unknown>;
  /** A true result means the test has fulfilled this route itself. */
  route?: (route: Route) => Promise<boolean>;
}
interface RecordedRequest { path: string; method: string; session: string; body: Record<string, unknown> }

/** Synthetic server state: private fields stay here; the browser stores opaque resume metadata. */
export async function mockFreshFlow(page: Page, token: string, options: FixtureOptions = {}) {
  const group = { id: "fresh-group", agency_id: "fresh-agency", name: "Synthetic Journey", token, status: "active", created_at: "2026-09-20T00:00:00Z", destination: "Singapore", travel_date: "2027-12-01", return_date: "2027-12-08", timezone: "Asia/Kolkata", departure_cities: [], custom_questions: [], custom_details: [], qualifier_relation_options: [], allow_files_from_device: true, require_selfie: false, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false, passport_required: false }, ...options.group };
  const drafts = new Map<string, FreshDraft>();
  const requests: RecordedRequest[] = [], unexpected: string[] = [], pageErrors: string[] = [];
  const completions: string[] = [], completeAttempts: Array<RecordedRequest & { draft: FreshDraft }> = [];
  const challenges = new Map<string, { id: string; email: string; phone: string }>();
  const qualifier = new Map<string, Record<string, unknown>>();
  const saves = new Map<string, FreshDraft>();
  const faults = { closed: false, startStatus: 0, deliveryFailure: false, rejectProofOnce: false, interruptCompletion: false, proofSeconds: 3600, extraction: "succeeded" as FreshDraft["extraction_status"] };
  let sequence = 0;
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.route("**/api/v1/**", async route => {
    if (await options.route?.(route)) return;
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    const session = request.headers()["x-upload-session-id"] ?? "";
    const body = request.headers()["content-type"]?.includes("application/json") ? request.postDataJSON() as Record<string, unknown> : {};
    const record = { path, method, session, body }; requests.push(record);
    if (path === `/api/v1/upload-links/token/${token}`) return faults.closed ? json(route, { detail: { code: "CLIENT_GROUP_CLOSED", message: "This link is closed." } }, 410) : json(route, group);
    if (path === "/api/v1/returning/capabilities") return json(route, { enabled: false, code_label: null });
    if (path.endsWith("/qualifier-selection")) {
      expect(session).toBeTruthy();
      if (method === "POST") qualifier.set(session, { ...body, selection_token: `qualifier-${session}` });
      return json(route, qualifier.get(session) ?? {});
    }
    if (path.endsWith("/prepare-file")) { expect(session).toBeTruthy(); return route.fulfill({ contentType: "image/jpeg", body: freshPreparedJpeg }); }
    const base = `/api/v1/public-drafts/${token}`;
    if (!path.startsWith(base)) { unexpected.push(`${method} ${path}`); return json(route, { detail: "Unexpected isolated request" }, 403); }
    expect(session).toBeTruthy();
    if (faults.closed) return json(route, { detail: { code: "CLIENT_GROUP_CLOSED", message: "This link is closed." } }, 410);
    if (path === base && method === "POST" && faults.startStatus) return json(route, { detail: faults.startStatus === 410 ? "This private draft has expired. Start a new traveller draft." : "Your saved draft is temporarily unavailable. Please retry." }, faults.startStatus);
    let draft = drafts.get(session);
    const resuming = Boolean(draft) && path === base && method === "POST";
    if (!draft) {
      draft = { id: `draft-${session}`, revision: 1, status: "active", expires_at: new Date(Date.now() + 86_400_000).toISOString(), passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, collection: null, verified_phone: null, documents: [], extracted_fields: {}, extraction_status: "none" };
      drafts.set(session, draft);
    }
    if (path.endsWith("/activity")) return json(route, { images_present: draft.documents.length > 0, presence_recorded: true, heartbeat_after_seconds: 60 });
    if (draft.status === "active" && (resuming || path.endsWith("/discard-documents"))) { draft.documents = []; draft.extraction_status = "none"; draft.ecr_status = "none"; draft.revision++; }
    if (path.endsWith("/discard-documents")) return json(route, draft);
    if (path.endsWith("/contact/request")) {
      if (faults.deliveryFailure) return json(route, { detail: "WhatsApp verification is temporarily unavailable. Try again." }, 503);
      const challenge = { id: `challenge-${++sequence}`, email: String(body.email), phone: String(body.phone_number) };
      challenges.set(session, challenge);
      return json(route, { challenge_id: challenge.id, expires_in_seconds: 300, resend_after_seconds: 60 });
    }
    if (path.endsWith("/contact/verify")) {
      const challenge = challenges.get(session);
      if (!challenge || challenge.id !== body.challenge_id || body.code !== "123456") return json(route, { detail: "Invalid or expired verification code" }, 400);
      draft.phone_verification_id = `proof-${session}-${++sequence}`;
      draft.phone_verification_expires_at = new Date(Date.now() + faults.proofSeconds * 1000).toISOString();
      draft.verified_phone = challenge.phone;
      return json(route, { phone_verification_id: draft.phone_verification_id, phone_number: challenge.phone, expires_in_seconds: faults.proofSeconds });
    }
    if (path.endsWith("/complete")) {
      completeAttempts.push({ ...record, draft: structuredClone(draft) });
      expect(body.expected_revision).toBe(draft.revision);
      expect(body.idempotency_key).toBeTruthy(); expect(body.information_confirmed).toBe(true);
      if (faults.rejectProofOnce) { faults.rejectProofOnce = false; return json(route, { detail: "Verify your WhatsApp number again before submitting." }, 400); }
      expect(body.phone_verification_id).toBe(draft.phone_verification_id);
      expect(Date.parse(draft.phone_verification_expires_at!)).toBeGreaterThan(Date.now());
      expect(draft.current_details.client_email).toBe(challenges.get(session)?.email);
      if (draft.status !== "submitted") completions.push(session);
      draft.status = "submitted"; draft.source_submission_id = `source-${session}`;
      if (faults.interruptCompletion) { faults.interruptCompletion = false; return route.abort("connectionreset"); }
      return json(route, { source_submission_id: draft.source_submission_id, status: "submitted" });
    }
    if (path.includes("/documents/")) {
      if (method === "GET") return route.fulfill({ contentType: "image/jpeg", body: freshPreparedJpeg, headers: { "cache-control": "private, no-store" } });
      expect(request.headers()["content-type"]).toContain("multipart/form-data; boundary=");
      expect(request.postData()).toContain('name="file"');
      draft.revision++; draft.documents = [{ id: `front-${++sequence}`, side: "front", state: "ready" }];
      draft.passport_fields = { ...freshFields }; draft.extraction_status = faults.extraction;
      return json(route, draft);
    }
    if (path !== base || !["GET", "POST", "PUT"].includes(method)) {
      unexpected.push(`${method} ${path}`); return json(route, { detail: "Unexpected isolated draft request" }, 403);
    }
    if (method === "PUT") {
      const key = `${session}:${body.idempotency_key}`;
      if (saves.has(key)) return json(route, saves.get(key));
      expect(body.expected_revision).toBe(draft.revision); expect(body.idempotency_key).toBeTruthy();
      Object.assign(draft, body, { revision: draft.revision + 1 }); saves.set(key, structuredClone(draft));
    }
    return json(route, draft);
  });
  return { group, drafts, requests, completions, completeAttempts, faults, unexpected, pageErrors };
}

export async function startFresh(page: Page, token: string, family = false) {
  await page.goto(`/upload/${token}`);
  await page.getByRole("button", { name: /New traveller/ }).click();
  await page.getByRole("button", { name: family ? "Family" : "Only me", exact: true }).click();
  await page.getByRole("button", { name: "Continue", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review your details", exact: true })).toBeVisible();
}

export async function fillFreshContact(page: Page, email = "asha@example.test", phone = "9900001234") {
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("WhatsApp number", { exact: true }).fill(phone);
}

export async function verifyFreshContact(page: Page, email = "asha@example.test", phone = "9900001234") {
  await fillFreshContact(page, email, phone);
  await page.getByRole("button", { name: "Verify WhatsApp number", exact: true }).click();
  await page.getByLabel("Verification code", { exact: true }).fill("123456");
  await page.getByRole("button", { name: "Confirm code", exact: true }).click();
  await expect(page.getByText("WhatsApp number verified", { exact: true })).toBeVisible();
}
