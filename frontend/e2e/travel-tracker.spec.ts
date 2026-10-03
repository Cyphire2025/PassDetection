import { expect, test } from "@playwright/test";
import { mockTravelTracker, trackerGroupId } from "./support/travel-tracker-api";

test("Documents opens the full group tracker, supports keyboard marking and preserves independent flight progress", async ({ page }) => {
  const api = await mockTravelTracker(page, 137, "super_admin");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/documents");
  await expect(page.getByRole("link", { name: "MCP", exact: true })).toHaveAttribute("href", "/admin/mcp");
  await page.getByRole("link", { name: "Open visa / flight tracker", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Visa / Flight Tracker", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Open tracker", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/documents/tracker/${trackerGroupId}$`));
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(page.getByRole("button", { name: "Imported Traveller: Mark visa applied", exact: true })).toBeVisible();
  const first = page.getByRole("button", { name: "Asha Patel: Mark visa applied", exact: true });
  await first.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Asha Patel: move to pending", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(api.passengers[0].visa_applied).toBe(true);
  expect(api.passengers[0].flight_booked).toBe(false);
  await page.getByRole("button", { name: "Next page", exact: true }).click();
  await expect(page.getByRole("button", { name: "Passenger 051: Mark visa applied", exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(page.getByRole("button", { name: "Asha Patel: move to pending", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("phone tracker fits the viewport and supports single tap marking", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const api = await mockTravelTracker(page, 1500);
  await page.goto(`/documents/tracker/${trackerGroupId}`);
  await page.getByRole("button", { name: "All", exact: true }).click();
  const first = page.getByRole("button", { name: "Asha Patel: Mark visa applied", exact: true });
  await expect(first).toBeVisible();
  await first.click();
  await expect(page.getByRole("button", { name: "Asha Patel: move to pending", exact: true })).toBeEnabled();
  expect(api.markRequests).toHaveLength(1);
  expect(api.passengers[0].visa_applied).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "../outputs/travel-tracker-phone.png", fullPage: false });
});

test("filtered bulk marking covers every page and Excel previews apply only reviewed matches", async ({ page }) => {
  const api = await mockTravelTracker(page);
  await page.goto(`/documents/tracker/${trackerGroupId}`);
  await page.getByRole("button", { name: "Mark filtered (137)", exact: true }).click();
  await page.getByRole("button", { name: "Mark filtered passengers", exact: true }).click();
  await expect(page.getByRole("heading", { name: "All visa passengers are marked" })).toBeVisible();
  expect(api.passengers.every((passenger) => passenger.visa_applied)).toBe(true);
  expect(api.markRequests).toEqual([{ track: "visa", marked: true, selection: { status: "pending", search: "" }, expected_count: 137 }]);
  await page.getByRole("tab", { name: "Flight bookings", exact: true }).click();
  await page.getByRole("button", { name: "Update from Excel / list", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Update flight from a list" });
  await dialog.getByRole("button", { name: "Paste names", exact: true }).click();
  await dialog.getByLabel("Passenger names to match").fill("Asha Patel\nDuplicate Name\nMissing Person");
  await dialog.getByRole("button", { name: "Preview matches", exact: true }).click();
  await expect(dialog.getByText("Two passengers share this name. Add a passport number.")).toBeVisible();
  await expect(dialog.getByText("No match in this group")).toBeVisible();
  expect(api.passengers.every((passenger) => !passenger.flight_booked)).toBe(true);
  await dialog.getByRole("button", { name: "Apply 1 matches", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  expect(api.passengers.filter((passenger) => passenger.flight_booked)).toHaveLength(1);
  for (const label of ["Marked Excel", "Pending Excel"]) {
    const download = page.waitForEvent("download");
    page.once("dialog", (prompt) => prompt.accept("tracker.xlsx"));
    await page.getByRole("button", { name: label, exact: true }).click();
    expect((await download).suggestedFilename()).toBe("tracker.xlsx");
  }
  await page.screenshot({ path: "../outputs/travel-tracker-desktop.png", fullPage: false });
});
