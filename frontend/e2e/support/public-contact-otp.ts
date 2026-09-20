import { expect, type Page, type Route } from "@playwright/test";

export const contactProofId = "00000000-0000-4000-8000-000000000001";

export async function mockPublicContactOtp(page: Page) {
  const requests: { path: string; body: Record<string, unknown>; credential?: string }[] = [];
  let phone = "";
  let counter = 0;
  let failDelivery = false;
  let challengeId = contactProofId;
  await page.route("**/contact-otp/*", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const body = request.postDataJSON() as Record<string, unknown>;
    requests.push({ path, body, credential: request.headers()["x-upload-session-id"] });
    const json = (data: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path.endsWith("/request")) {
      if (failDelivery) return json({ detail: "WhatsApp verification is temporarily unavailable. Try again." }, 503);
      const digits = String(body.phone_number).replace(/\D/g, "");
      phone = digits.length === 10 ? `+91${digits}` : `+${digits}`;
      challengeId = `00000000-0000-4000-8000-${String(++counter).padStart(12, "0")}`;
      return json({ challenge_id: challengeId, expires_in_seconds: 300, resend_after_seconds: 60 });
    }
    if (path.endsWith("/verify")) {
      if (body.code !== "123456") return json({ detail: "Invalid or expired verification code" }, 401);
      return json({ phone_verification_id: challengeId, phone_number: phone, expires_in_seconds: 3600 });
    }
    return json({ detail: "Unexpected OTP request" }, 400);
  });
  return { requests, setDeliveryFailure(value: boolean) { failDelivery = value; } };
}

export async function verifyPublicContact(page: Page, email = "aarav@example.com", phone = "+919900001234") {
  await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
  await page.getByRole("textbox", { name: "WhatsApp active number", exact: true }).fill(phone);
  await page.getByRole("button", { name: "Send OTP", exact: true }).click();
  await page.getByRole("textbox", { name: /6-digit.*code|verification code|OTP/i }).fill("123456");
  await page.getByRole("button", { name: /Verify.*continue/i }).click();
}

export async function expectNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}
