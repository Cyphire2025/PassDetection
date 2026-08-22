import { expect, test, type Page, type Route } from "@playwright/test";

const activationToken = "activation-token-0123456789abcdef0123456789abcdef0123456789abcdef";
const recoveryToken = "recovery-token-0123456789abcdef0123456789abcdef0123456789abcdef";
const admin = {
  id: "e2e-admin",
  email: "admin@example.test",
  full_name: "E2E Agency Admin",
  role: "agency_admin",
  agency_id: "agency-e2e",
  is_active: true,
  last_login_at: null,
  created_at: "2026-08-22T00:00:00Z",
  updated_at: "2026-08-22T00:00:00Z",
  capabilities: [],
};

async function fulfill(route: Route, body: unknown, headers = {}) {
  await route.fulfill({
    status: 200,
    headers: { "content-type": "application/json", ...headers },
    body: JSON.stringify(body),
  });
}

async function installAdminSession(page: Page, onStaffInvite: (body: unknown) => void) {
  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/refresh") {
      await fulfill(route, {
        status: "authenticated",
        user: admin,
        token_type: "bearer",
        access_token_expires_at: "2099-08-22T13:00:00Z",
      });
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await fulfill(route, admin);
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await fulfill(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    if (pathname === "/api/v1/admin/accounts/staff" && request.method() === "POST") {
      onStaffInvite(request.postDataJSON());
      await fulfill(route, {
        id: "e2e-staff",
        full_name: "Invited Staff",
        email: "invited.staff@example.test",
        role: "agency_staff",
        agency_id: "agency-e2e",
        agency_name: null,
        is_active: true,
        created_at: "2026-08-22T00:00:00Z",
        last_login_at: null,
        credential_state: "invited",
        activation_token: activationToken,
      });
      return;
    }
    if (request.method() === "GET") {
      await fulfill(route, []);
      return;
    }
    await fulfill(route, {});
  });
}

test("an administrator invites staff without choosing or receiving their password", async ({ page }) => {
  let invitationBody: unknown = null;
  await installAdminSession(page, (body) => { invitationBody = body; });
  await page.goto("/staff");

  await page.getByRole("button", { name: "Create Staff" }).first().click();
  await expect(page.getByRole("heading", { name: "Create Staff" })).toBeVisible();
  await page.getByLabel("Full name").fill("Invited Staff");
  await page.getByPlaceholder("staff@company.com").fill("invited.staff@example.test");
  await page.getByRole("button", { name: "Create Staff" }).last().click();

  await expect(page.getByRole("heading", { name: "Staff activation link created" })).toBeVisible();
  await expect(page.getByText(new RegExp(`/activate\\?token=${activationToken}`))).toBeVisible();
  expect(invitationBody).toEqual({
    full_name: "Invited Staff",
    email: "invited.staff@example.test",
  });
  expect(invitationBody).not.toHaveProperty("password");
});

test("a Client Manager is created through the same passwordless invitation boundary", async ({ page }) => {
  const gcAdmin = { ...admin, capabilities: ["gc_app.manage"] };
  let managerBody: Record<string, unknown> | null = null;
  await page.context().addCookies([{
    name: "access_token",
    value: "e2e-session",
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    if (pathname === "/api/v1/auth/refresh") {
      await fulfill(route, {
        status: "authenticated",
        user: gcAdmin,
        token_type: "bearer",
        access_token_expires_at: "2099-08-22T13:00:00Z",
      });
      return;
    }
    if (pathname === "/api/v1/auth/me") {
      await fulfill(route, gcAdmin);
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await fulfill(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    if (pathname === "/api/v1/gc-app/admin/client-managers" && request.method() === "GET") {
      await fulfill(route, { items: [], total: 0, offset: 0, limit: 20 });
      return;
    }
    if (pathname === "/api/v1/gc-app/admin/client-organizations/search") {
      await fulfill(route, {
        items: [{ id: "company-e2e", name: "Acme Travel", status: "active" }],
        total: 1,
        offset: 0,
        limit: 50,
      });
      return;
    }
    if (pathname === "/api/v1/gc-app/admin/groups" && request.method() === "GET") {
      await fulfill(route, {
        items: [{
          id: "group-e2e",
          name: "Singapore 2026",
          destination: "Singapore",
          travel_date: "2026-11-01",
          return_date: "2026-11-08",
          lifecycle_status: "active",
          gc_enabled: true,
          client_organization_id: "company-e2e",
          client_organization_name: "Acme Travel",
        }],
        total: 1,
        offset: 0,
        limit: 50,
      });
      return;
    }
    if (pathname === "/api/v1/gc-app/admin/client-managers" && request.method() === "POST") {
      managerBody = request.postDataJSON() as Record<string, unknown>;
      await fulfill(route, {
        id: "manager-e2e",
        full_name: "Client Manager",
        email: "client.manager@example.test",
        phone_number: "+919900001111",
        organization_id: "company-e2e",
        organization_name: "Acme Travel",
        status: "invited",
        revision: 1,
        group_ids: ["group-e2e"],
        assigned_groups: [],
        last_login_at: null,
        created_at: "2026-08-22T00:00:00Z",
        updated_at: "2026-08-22T00:00:00Z",
        temporary_password: null,
        activation_token: activationToken,
      });
      return;
    }
    await fulfill(route, request.method() === "GET" ? [] : {});
  });

  await page.goto("/gc-app/client-manager-accounts");
  await expect(page.getByRole("heading", { name: "Client Manager Accounts" })).toBeVisible();
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("dialog", { name: "Create Client Manager" })).toBeVisible();
  await expect(page.locator('input[type="password"]')).toHaveCount(0);
  await page.locator('input[name="name"]').fill("Client Manager");
  await page.locator('input[name="email"]').fill("client.manager@example.test");
  await page.locator('input[name="phone_number"]').fill("+919900001111");
  await page.getByRole("combobox", { name: /Assigned company\/client/ }).click();
  await page.getByRole("option", { name: "Acme Travel" }).click();
  await page.getByRole("button", { name: /Singapore 2026.*Assign/ }).click();
  await page.getByRole("button", { name: "Create account" }).last().click();

  await expect(page.getByRole("dialog", { name: "Activation link created" })).toBeVisible();
  await expect(page.getByText(new RegExp(`/gc/activate\\?token=${activationToken}`))).toBeVisible();
  expect(managerBody).not.toBeNull();
  expect(managerBody).not.toHaveProperty("password");
  expect(managerBody).toMatchObject({
    full_name: "Client Manager",
    email: "client.manager@example.test",
    phone_number: "+919900001111",
    organization_id: "company-e2e",
    group_ids: ["group-e2e"],
    invitation_flow: true,
    return_activation_token_once: true,
    return_temporary_password_once: false,
  });
});

test("the invited user chooses a password and enrolls MFA before receiving a session", async ({ page }) => {
  let activationBody: unknown = null;
  let mfaBody: unknown = null;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/activate") {
      activationBody = request.postDataJSON();
      await fulfill(route, {
        status: "mfa_enrollment_required",
        challenge_token: "mfa-challenge-token",
        expires_at: "2099-08-22T13:00:00Z",
        setup_secret: "JBSWY3DPEHPK3PXP",
        otpauth_uri: "otpauth://totp/PassDetection:e2e?secret=JBSWY3DPEHPK3PXP",
      });
      return;
    }
    if (pathname === "/api/v1/auth/mfa/verify") {
      mfaBody = request.postDataJSON();
      await fulfill(route, {
        status: "authenticated",
        user: { ...admin, id: "e2e-staff", email: "invited.staff@example.test", role: "agency_staff" },
        token_type: "bearer",
        access_token_expires_at: "2099-08-22T13:00:00Z",
        recovery_codes: ["recovery-one", "recovery-two"],
      }, {
        "set-cookie": "access_token=e2e-session; Path=/; HttpOnly; SameSite=Lax",
      });
      return;
    }
    if (pathname === "/api/v1/auth/refresh") {
      await fulfill(route, {
        status: "authenticated",
        user: { ...admin, id: "e2e-staff", email: "invited.staff@example.test", role: "agency_staff" },
        token_type: "bearer",
        access_token_expires_at: "2099-08-22T13:00:00Z",
      });
      return;
    }
    if (pathname === "/api/v1/dashboard/stats") {
      await fulfill(route, { total_passports: 0, pending_review: 0, confirmed: 0, active_links: 0, recent_submissions: [] });
      return;
    }
    if (pathname === "/api/v1/notifications/feed") {
      await fulfill(route, { items: [], unread_count: 0, next_cursor: null });
      return;
    }
    await fulfill(route, request.method() === "GET" ? [] : {});
  });

  await page.goto(`/activate?token=${activationToken}`);
  const passwords = page.locator('input[autocomplete="new-password"]');
  await passwords.nth(0).fill("UserChosenPassword9");
  await passwords.nth(1).fill("UserChosenPassword9");
  await page.getByRole("button", { name: "Set password and continue" }).click();

  await expect(page.getByRole("heading", { name: "Protect your account" })).toBeVisible();
  await expect(page.getByText("JBSWY3DPEHPK3PXP")).toBeVisible();
  await page.locator("#mfa-code").fill("123456");
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { name: "Save your recovery codes" })).toBeVisible();
  await page.getByRole("button", { name: "I saved these codes" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);

  expect(activationBody).toEqual({ token: activationToken, new_password: "UserChosenPassword9" });
  expect(mfaBody).toEqual({ challenge_token: "mfa-challenge-token", code: "123456" });
});

test("password recovery is enumeration-safe and requires the existing factor after reset", async ({ page }) => {
  let requestBody: unknown = null;
  let completionBody: unknown = null;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/v1/auth/password/recovery/request") {
      requestBody = request.postDataJSON();
      await fulfill(route, {
        message: "If an eligible account exists, recovery instructions have been issued.",
        development_recovery_token: recoveryToken,
      });
      return;
    }
    if (pathname === "/api/v1/auth/password/recovery/complete") {
      completionBody = request.postDataJSON();
      await fulfill(route, {
        status: "mfa_required",
        challenge_token: "recovery-mfa-challenge",
        expires_at: "2099-08-22T13:00:00Z",
        setup_secret: null,
        otpauth_uri: null,
      });
      return;
    }
    await fulfill(route, {});
  });

  await page.goto("/forgot-password");
  await page.getByLabel("Email address").fill("unknown-or-real@example.test");
  await page.getByRole("button", { name: "Request recovery" }).click();
  await expect(page.getByText("If an eligible account exists, recovery instructions have been issued.")).toBeVisible();
  await page.getByRole("link", { name: "Continue with the development recovery link" }).click();
  await expect(page.getByRole("heading", { name: "Choose a new password" })).toBeVisible();

  const passwords = page.locator('input[autocomplete="new-password"]');
  await passwords.nth(0).fill("RecoveredPassword9");
  await passwords.nth(1).fill("RecoveredPassword9");
  await page.getByRole("button", { name: "Reset password and continue" }).click();
  await expect(page.getByRole("heading", { name: "Verify your identity" })).toBeVisible();

  expect(requestBody).toEqual({ email: "unknown-or-real@example.test" });
  expect(completionBody).toEqual({ token: recoveryToken, new_password: "RecoveredPassword9" });
});
