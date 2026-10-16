import { expect, test, type Page } from "@playwright/test";
import {
  broadcastId,
  historyEntry,
  setupWorkspace,
} from "./support/whatsapp-workspace-fixture";

const base = `/whatsapp/${broadcastId}/history`;

async function setupTypeReports(page: Page) {
  const fixture = await setupWorkspace(page);
  const counts = { all: 12, sent: 9, not_sent: 1, delivery_left: 2, failed: 2 };
  const kinds = [
    "welcome",
    "passport_link",
    "reminder",
    "group_invite",
    "document_update",
  ];
  await page.route(
    "**/api/v1/whatsapp/groups/*/message-types**",
    async (route) => {
      const url = new URL(route.request().url());
      const reply = (body: unknown) => route.fulfill({ json: body });
      if (url.pathname.endsWith("/message-types"))
        return reply(
          kinds.map((message_type) => ({
            message_type,
            counts,
            never_attempted: 1,
            send_count: 2,
            version_count: 2,
            legacy_record_count: 0,
            total_attempts: 24,
            accepted_attempts: 18,
            last_sent_at: historyEntry.created_at,
          })),
        );
      const kind = url.pathname.split("/").at(-2)!;
      if (url.pathname.endsWith("/versions")) {
        const items = [2, 1].map((version_number) => ({
          ...historyEntry,
          id: `${kind}-v${version_number}`,
          message_type: kind,
          message_preview: "Please submit your documents before Friday.",
          version_number,
          created_at: `2026-10-${version_number === 2 ? "16" : "13"}T10:30:00Z`,
        }));
        return reply({ items, total: items.length, offset: 0, limit: 25 });
      }
      const filter = url.searchParams.get("status_filter") || "all";
      const q = (url.searchParams.get("q") || "").toLowerCase();
      const items = fixture.group.recipients
        .map((person, i) => ({
          recipient_id: person.id,
          name: person.name,
          phone_number: person.normalized_phone_number,
          status:
            i === 0 ? "not_sent" : i < 3 ? "failed" : i < 5 ? "sent" : "read",
          message_id: i === 0 ? null : `${kind}-v2`,
          message_log_id: i === 0 ? null : `type-log-${i}`,
          updated_at: i === 0 ? null : historyEntry.updated_at,
          error_message: i === 1 ? "Please check the WhatsApp number." : null,
        }))
        .filter(
          (person) =>
            (filter === "all" ||
              (filter === "sent" && ["read", "sent"].includes(person.status)) ||
              (filter === "delivery_left" && person.status === "sent") ||
              person.status === filter) &&
            (!q ||
              person.name.toLowerCase().includes(q) ||
              person.phone_number.includes(q)),
        );
      return reply({
        items,
        total: items.length,
        counts,
        offset: 0,
        limit: 50,
      });
    },
  );
  return fixture;
}

test("type totals complement every-send history, with separate identical versions for repeatable messages", async ({
  page,
}) => {
  const fixture = await setupTypeReports(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(base);
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
  await page
    .getByRole("link", { name: "By message type", exact: true })
    .click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(6);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/11-type-overview.png",
    fullPage: true,
  });
  for (const [label, kind] of [
    ["Reminder", "reminder"],
    ["Group invite", "group_invite"],
    ["Trip update", "document_update"],
  ]) {
    await page
      .getByRole("link", { name: `View ${label} overall delivery` })
      .click();
    const report = page.getByRole("region", {
      name: "Overall message recipients",
    });
    await expect(
      report.getByRole("button", { name: "All 12", exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Versions (2)", exact: true }).click();
    const versions = page.getByRole("region", { name: "Message versions" });
    await expect(
      versions.getByText("Version 1", { exact: true }),
    ).toBeVisible();
    await expect(
      versions.getByText("Version 2", { exact: true }),
    ).toBeVisible();
    await expect(
      versions.getByText("Please submit your documents before Friday.", {
        exact: true,
      }),
    ).toHaveCount(2);
    await expect(
      versions.getByRole("link", { name: "View delivery for version 1" }),
    ).toHaveAttribute("href", `${base}?message=${kind}-v1`);
    if (kind === "reminder")
      await page.screenshot({
        path: "../output/whatsapp-workspace-qa/12-reminder-versions.png",
        fullPage: true,
      });
    await page
      .getByRole("link", { name: "All message types", exact: true })
      .click();
  }
  await page.getByRole("link", { name: "Every send", exact: true }).click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
  expect(fixture.mutations).toEqual([]);
  expect(fixture.errors).toEqual([]);
});

test("overall recipient filters include never-sent people and allow number correction", async ({
  page,
}) => {
  const fixture = await setupTypeReports(page);
  await page.goto(`${base}?view=types&type=welcome`);
  const report = page.getByRole("region", {
    name: "Overall message recipients",
  });
  await report.getByRole("button", { name: "Not sent 1", exact: true }).click();
  await expect(report.getByRole("table").getByRole("row")).toHaveCount(2);
  await expect(
    report.getByText("No send recorded", { exact: true }),
  ).toBeVisible();
  await expect(report.getByText("Aarav Shah", { exact: true })).toBeVisible();
  await report.getByRole("button", { name: "Failed 2", exact: true }).click();
  await page
    .getByRole("searchbox", { name: "Search overall recipients" })
    .fill("Diya");
  await expect(report.getByRole("table").getByRole("row")).toHaveCount(2);
  await report
    .getByRole("button", { name: "Edit WhatsApp number 919800000001" })
    .click();
  await report
    .getByRole("textbox", { name: "New WhatsApp number" })
    .fill("+919900000099");
  await report.getByRole("button", { name: "Save WhatsApp number" }).click();
  await expect.poll(() => fixture.mutations.length).toBe(1);
  expect(fixture.mutations[0].body.phone_number).toBe("+919900000099");
  await expect(report.getByText("919900000099", { exact: true })).toBeVisible();
  expect(fixture.errors).toEqual([]);
});

test("two long detail cards remain divided and scroll independently at desktop heights", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  for (const person of fixture.group.recipients.slice(0, 2))
    Object.assign(
      person.imported_fields,
      Object.fromEntries(
        Array.from({ length: 30 }, (_, i) => [
          `additional_field_${i}`,
          `Imported detail ${i} for ${person.name}`,
        ]),
      ),
    );
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(`/whatsapp/${broadcastId}/recipients`);
  for (const name of ["Aarav Shah", "Diya Mehta"]) {
    await page.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();
  }
  const firstCard = page.getByRole("region", {
    name: "Details for Aarav Shah",
    exact: true,
  });
  const secondCard = page.getByRole("region", {
    name: "Details for Diya Mehta",
    exact: true,
  });
  const firstBody = page.getByRole("region", {
    name: "Detail fields for Aarav Shah",
    exact: true,
  });
  const secondBody = page.getByRole("region", {
    name: "Detail fields for Diya Mehta",
    exact: true,
  });
  for (const viewport of [
    { width: 1536, height: 1100 },
    { width: 1366, height: 900 },
  ]) {
    await page.setViewportSize(viewport);
    await secondCard.getByRole("heading").scrollIntoViewIfNeeded();
    const firstBox = await firstCard.boundingBox();
    const secondBox = await secondCard.boundingBox();
    expect(firstBox!.width).toBeGreaterThanOrEqual(340);
    expect(secondBox!.y).toBeGreaterThanOrEqual(
      firstBox!.y + firstBox!.height + 12,
    );
    await expect(firstCard.getByRole("heading")).toBeInViewport();
    await expect(secondCard.getByRole("heading")).toBeInViewport();
    const outerScroll = await page.evaluate(() => window.scrollY);
    await firstBody.hover();
    await page.mouse.wheel(0, 350);
    await expect
      .poll(() => firstBody.evaluate((element) => element.scrollTop))
      .toBeGreaterThan(0);
    expect(await secondBody.evaluate((element) => element.scrollTop)).toBe(0);
    expect(await page.evaluate(() => window.scrollY)).toBe(outerScroll);
    await expect(firstCard.getByRole("heading")).toBeInViewport();
    await expect(secondCard.getByRole("heading")).toBeInViewport();
    await firstBody.evaluate((element) => {
      element.scrollTop = 0;
    });
  }
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/13-independent-details.png",
    fullPage: true,
  });
  expect(fixture.errors).toEqual([]);
});

test("type reports and version tables fit the mobile page width", async ({
  page,
}) => {
  await setupTypeReports(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const suffix of [
    "?view=types",
    "?view=types&type=reminder",
    "?view=types&type=reminder&report=versions",
  ]) {
    await page.goto(`${base}${suffix}`);
    await expect(
      page.getByRole("navigation", { name: "Delivery history views" }),
    ).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
});
