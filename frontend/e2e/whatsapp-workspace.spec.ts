import { expect, test } from "@playwright/test";
import {
  batchId,
  broadcastId,
  setupWorkspace,
} from "./support/whatsapp-workspace-fixture";

const base = `/whatsapp/${broadcastId}`;

test("broadcasts open into five coherent pages with editor and preview before recipients", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto("/whatsapp");
  await expect(
    page.getByRole("heading", { name: "WhatsApp broadcasts" }),
  ).toBeVisible();
  await expect(page.getByText("CURRENT BATCH", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/01-broadcasts.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Open Dubai · October delegates" })
    .click();
  await expect(
    page
      .getByRole("navigation", { name: "Broadcast sections" })
      .getByRole("link"),
  ).toHaveCount(5);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/02-message-library.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: /^Text trip update Write a text update/ })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Update message" }),
  ).toHaveValue(/airport transfer/);
  await page
    .getByRole("textbox", { name: "Update message" })
    .fill(
      "Your departure time is now 10:30. Please arrive at Terminal 3 by 07:30.",
    );
  await expect(page.getByLabel("Live WhatsApp preview")).toContainText(
    "Your departure time is now 10:30",
  );
  const editor = await page
    .getByRole("region", { name: "Message editor and preview" })
    .boundingBox();
  const audience = await page
    .getByRole("region", { name: "Message audience" })
    .boundingBox();
  expect(editor!.y).toBeLessThan(audience!.y);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/03-compose-update.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Deselect matching" }).click();
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Select all matching" }).click();
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Document submission", exact: true })
    .selectOption("not_submitted");
  await expect
    .poll(() => fixture.previews.at(-1)?.update_submission)
    .toBe("not_submitted");
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Review message", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Send 3 messages" })
    .click();
  await expect(page).toHaveURL(new RegExp(`/history\\?message=${batchId}`));
  expect(
    fixture.mutations.find((item) => item.path.endsWith("/send"))?.body
      .update_submission,
  ).toBe("not_submitted");
  expect(fixture.errors).toEqual([]);
});

test("released document-status trip updates keep their preview and dispatch flow", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto("/whatsapp");
  await expect(
    page.getByRole("heading", { name: "WhatsApp broadcasts" }),
  ).toBeVisible();
  await expect(page.getByText("CURRENT BATCH", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/01-broadcasts.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Open Dubai · October delegates" })
    .click();
  await expect(
    page
      .getByRole("navigation", { name: "Broadcast sections" })
      .getByRole("link"),
  ).toHaveCount(5);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/02-message-library.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: /^Trip update Send an update/ })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Update message" }),
  ).toHaveValue("");
  await page
    .getByRole("textbox", { name: "Update message" })
    .fill(
      "Your departure time is now 10:30. Please arrive at Terminal 3 by 07:30.",
    );
  await expect(page.getByLabel("Live WhatsApp preview")).toContainText(
    "Your departure time is now 10:30",
  );
  const editor = await page
    .getByRole("region", { name: "Message editor and preview" })
    .boundingBox();
  const audience = await page
    .getByRole("region", { name: "Message audience" })
    .boundingBox();
  expect(editor!.y).toBeLessThan(audience!.y);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/03-compose-update.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Select all" }).click();
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("combobox", { name: "Document submission", exact: true })
    .selectOption("not_submitted");
  await expect
    .poll(() => fixture.previews.at(-1)?.submission_status)
    .toBe("not_submitted");
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Review message", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Send 3 messages" })
    .click();
  await expect(page).toHaveURL(new RegExp(`/history\\?message=${batchId}`));
  expect(
    (fixture.mutations.find((item) => item.path.endsWith("/send"))?.body.audience as { submission_status: string }).submission_status,
  ).toBe("not_submitted");
  expect(fixture.errors).toEqual([]);
});

test("100 library entries stay searchable and paginated", async ({ page }) => {
  await setupWorkspace(page, { largeCatalog: true });
  await page.goto(base);
  await expect(
    page.getByRole("button", { name: /^Travel update/ }),
  ).toHaveCount(18);
  await page
    .getByRole("navigation", { name: "Message library pagination" })
    .getByRole("button", { name: "Next" })
    .click();
  await expect(
    page.getByRole("button", { name: /^Travel update 019/ }),
  ).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search message library" })
    .fill("100");
  await expect(
    page.getByRole("button", { name: /^Travel update/ }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: /^Travel update 100/ }).click();
  await expect(
    page.getByRole("textbox", { name: "Update message" }),
  ).toBeVisible();
});

test("recipients support failed-number correction and stacked detail panels", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(`${base}/recipients`);
  for (const name of ["Aarav Shah", "Diya Mehta"]) {
    await page.getByRole("button", { name: `Actions for ${name}` }).click();
    await page.getByRole("menuitem", { name: "View details" }).click();
  }
  await expect(
    page.getByRole("region", { name: "Details for Aarav Shah" }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Details for Diya Mehta" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/04-recipients-compare.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: /^Welcome failed/ }).click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Edit WhatsApp number 919800000001" })
    .click();
  await page
    .getByRole("textbox", { name: "New WhatsApp number" })
    .fill("+919900000099");
  await page.getByRole("button", { name: "Save WhatsApp number" }).click();
  await expect.poll(() => fixture.mutations.length).toBe(1);
  expect(fixture.mutations[0].body.phone_number).toBe("+919900000099");
  await page
    .getByRole("button", { name: "Add recipients", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText("Import");
  expect(fixture.errors).toEqual([]);
});

test("each send has a report and retry preserves the selected saved message identity", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page, { failFirstResend: true });
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(`${base}/history`);
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/05-history.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: /^View delivery for/ })
    .first()
    .click();
  await page.getByRole("button", { name: "View message", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Message content" })).toContainText("Airport transfer details");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /^Failed/ }).click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
  await expect(page.getByText("Unconfirmed", { exact: true })).toBeVisible();
  await expect(page.getByText("Need Review", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/06-delivery-report.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Saved airport transfer details",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Send to this recipient", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Check resend status", exact: true })
    .click();
  await expect.poll(() => fixture.mutations.length).toBe(2);
  expect(fixture.mutations[0].body).toEqual(fixture.mutations[1].body);
  expect(fixture.mutations[0].body.source_message_log_id).toBe("log-1");
  expect(fixture.errors).toEqual([]);
});

test("documents stay scoped to the open broadcast and retain every filter", async ({
  page,
}) => {
  await setupWorkspace(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(`${base}/documents`);
  await expect(page.getByText("Aarav Shah", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Unrelated passenger must stay hidden"),
  ).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("combobox")).toHaveCount(1);
  for (const filter of [
    "All",
    "Multiple PDFs",
    "Shared PDF",
    "Assigned",
    "Missing",
    "Sent",
    "Not sent",
  ])
    await expect(
      page.getByRole("button", { name: new RegExp(`^${filter}`) }),
    ).toBeVisible();
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/07-documents.png",
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Broadcast details", exact: true })
    .click();
  await expect(
    page.getByRole("textbox", { name: "Broadcast name" }),
  ).toHaveValue("Dubai · October delegates");
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/08-broadcast-details.png",
    fullPage: true,
  });
});

test("document messages use the shared editor and send only the selected broadcast's frozen targets", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  await page.setViewportSize({ width: 1536, height: 1100 });
  await page.goto(`${base}/documents`);
  await page
    .getByRole("button", { name: "Send documents", exact: true })
    .click();
  const editor = page.getByRole("textbox", {
    name: "Document message",
    exact: true,
  });
  await expect(editor).toHaveValue("Your travel documents are attached.");
  await editor.fill(
    "Your approved visa is attached. Keep a printed copy with you.",
  );
  await expect(page.getByLabel("Search document recipients")).toBeVisible();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(4);
  await expect(page.getByTestId("broadcast-message-preview")).toContainText(
    "Your approved visa is attached",
  );
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/10-document-composer.png",
    fullPage: true,
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Review message", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Send 2 messages", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Passenger documents" }),
  ).toBeVisible();
  expect(fixture.mutations[0].body).toMatchObject({
    document_ids: ["doc-1", "doc-2"],
    resend_document_ids: [],
    preview_token: "frozen-preview-token",
    message_content_1:
      "Your approved visa is attached. Keep a printed copy with you.",
  });
  expect(fixture.errors).toEqual([]);
});

test("reminder targeting and new passport-link audiences keep their specific options in the shared composer", async ({
  page,
}) => {
  const fixture = await setupWorkspace(page);
  await page.goto(base);
  await page.getByRole("button", { name: /^Reminder Follow up/ }).click();
  await page
    .getByRole("radio", { name: "Only people who haven’t submitted" })
    .check();
  await expect
    .poll(() => fixture.previews.at(-1)?.audience)
    .toBe("not_submitted");
  expect(fixture.previews.at(-1)?.audience_client_group_id).toBe("source-trip");
  await expect(
    page.getByRole("button", { name: "Review message", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Message library", exact: true })
    .click();
  await page.getByRole("button", { name: /^Passport link Share/ }).click();
  await expect(
    page.getByRole("checkbox", { name: "Select Aarav Shah", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("checkbox", {
      name: /^Include people who received a previous passport link/,
    })
    .check();
  await expect(
    page.getByRole("checkbox", { name: "Select Aarav Shah", exact: true }),
  ).toBeChecked();
  await expect
    .poll(() => fixture.previews.at(-1)?.include_previous_recipients)
    .toBe(true);
  expect(fixture.errors).toEqual([]);
});

test("mobile workspace has no page-level horizontal overflow", async ({
  page,
}) => {
  await setupWorkspace(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of [
    base,
    `${base}/recipients`,
    `${base}/history`,
    `${base}/documents`,
    `${base}/details`,
  ]) {
    await page.goto(path);
    await expect(
      page.getByRole("navigation", { name: "Broadcast sections" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
  }
  await page.screenshot({
    path: "../output/whatsapp-workspace-qa/09-mobile.png",
    fullPage: true,
  });
});
