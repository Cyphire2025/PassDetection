import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const id = "00000000-0000-4000-8000-000000000021";
const token = `gcmcp_transfer_${"a".repeat(48)}`;
const bytes = Buffer.from("%PDF-fixture original");
const sha256 = createHash("sha256").update(bytes).digest("hex");

async function setup(page: Page, upload = false, corrupt = false, expired = false, workbook = false) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const errors: string[] = [];
  let status = "pending";
  let downloaded = false;
  let delivered = false;
  let wait: Promise<void> | null = null;
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => { Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: undefined }); });
  await page.context().addCookies([{ name: "access_token", value: "not-transfer-authority", domain: "127.0.0.1", path: "/", httpOnly: true }]);
  await page.route("**/api/v1/auth/**", () => { throw new Error("Public file transfer must not sign in."); });
  const mediaType = workbook ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/pdf";
  const metadata = () => ({ id, kind: upload ? workbook ? "upload_workbook" : "upload_pdf" : "download", purpose: upload ? workbook ? "group_workbook" : "document_pdf" : "export", status,
    filename: upload ? workbook ? "Group workbook.xlsx" : "Travel documents.pdf" : "Passenger report.pdf", media_type: mediaType, byte_size: bytes.length, sha256,
    expires_at: expired ? "2020-10-03T00:10:00Z" : "2099-10-03T00:10:00Z", destination_label: "Prepared tour group",
    agency_id: null, group_id: null, document_type: upload && !workbook ? "visa" : null, download_completed: downloaded, delivered });
  await page.route("**/mcp/native-transfers/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    const headers = await request.allHeaders();
    expect(headers.authorization).toBe(`Bearer ${token}`);
    expect(headers.cookie).toBeUndefined(); expect(headers.referer).toBeUndefined();
    expect(request.url()).not.toContain(token);
    calls.push({ method, path, body: method === "POST" ? request.postDataJSON() : null });
    if (path.endsWith("/content") && method === "GET") {
      downloaded = true; status = "completed";
      return route.fulfill({ status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=\"Passenger report.pdf\"" }, body: corrupt ? Buffer.alloc(bytes.length, 1) : bytes });
    }
    if (path.endsWith("/content") && method === "PUT") {
      expect(headers["content-type"]).toBe(mediaType);
      expect(request.postDataBuffer()).toEqual(bytes);
      if (wait) await wait;
      status = "completed";
    }
    if (path.endsWith("/delivery")) { expect(method).toBe("POST"); expect(downloaded).toBe(true); delivered = true; }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(metadata()) });
  });
  return { calls, errors, holdUpload: () => {
    let release!: () => void; wait = new Promise<void>((resolve) => { release = resolve; });
    return () => { release(); wait = null; };
  } };
}

for (const width of [1440, 390]) {
  test(`verified private download requires save confirmation at ${width}px`, async ({ page }, testInfo) => {
    const state = await setup(page); await page.setViewportSize({ width, height: 950 });
    await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
    await expect(page.getByRole("heading", { name: "Save your prepared file", exact: true })).toBeVisible();
    await expect(page.getByText("Passenger report.pdf", { exact: true })).toBeVisible();
    expect(new URL(page.url()).hash).toBe(""); expect(await page.locator("body").innerText()).not.toContain(token);
    await expect(page.locator('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");
    await page.getByRole("button", { name: "Prepare download", exact: true }).click();
    await expect(page.getByText("File checked and ready to save.", { exact: true })).toBeVisible();
    expect(state.calls.filter((item) => item.method === "POST")).toHaveLength(0);
    const [file] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Save file", exact: true }).click()]);
    expect(file.suggestedFilename()).toBe("Passenger report.pdf");
    expect(createHash("sha256").update(await readFile((await file.path())!)).digest("hex")).toBe(sha256);
    expect(state.calls.filter((item) => item.method === "POST")).toHaveLength(0);
    await expect(page.getByRole("button", { name: "I saved this file", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    const screenshot = testInfo.outputPath(`mcp-download-confirmation-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`Download confirmation ${width}px`, { path: screenshot, contentType: "image/png" });
    await page.getByRole("button", { name: "I saved this file", exact: true }).click();
    await expect(page.getByRole("heading", { name: "File saved and confirmed", exact: true })).toBeVisible();
    expect(state.calls.filter((item) => item.method === "POST")).toEqual([{ method: "POST", path: `/mcp/native-transfers/${id}/delivery`, body: { byte_size: bytes.length, sha256 } }]);
    expect(state.errors).toEqual([]);
  });

  test(`upload verifies the exact prepared file and preserves its destination at ${width}px`, async ({ page }, testInfo) => {
    const workbook = width === 390;
    const mediaType = workbook ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" : "application/pdf";
    const extension = workbook ? "xlsx" : "pdf";
    const state = await setup(page, true, false, false, workbook); await page.setViewportSize({ width, height: 950 });
    await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
    await expect(page.getByText("Prepared tour group", { exact: true })).toBeVisible();
    await expect(page.getByText(workbook ? "Group workbook import" : "visa", { exact: true })).toBeVisible();
    const input = page.getByLabel(`Choose the prepared ${extension.toUpperCase()} file`, { exact: true });
    await input.setInputFiles({ name: `wrong.${extension}`, mimeType: mediaType, buffer: Buffer.alloc(bytes.length, 1) });
    await page.getByRole("button", { name: "Verify and upload", exact: true }).click();
    await expect(page.getByRole("region", { name: "MCP file transfer" }).getByRole("alert")).toContainText("does not match");
    expect(state.calls.filter((item) => item.method === "PUT")).toHaveLength(0);
    await input.setInputFiles({ name: `Original renamed file.${extension}`, mimeType: mediaType, buffer: bytes });
    const release = state.holdUpload();
    try {
      await page.getByRole("button", { name: "Verify and upload", exact: true }).click();
      // Disabled controls precede the asynchronous upload; wait for the held route itself.
      await expect.poll(() => state.calls.filter((item) => item.method === "PUT")).toHaveLength(1);
      await expect(page.getByRole("button", { name: "Verify and upload", exact: true })).toBeDisabled();
      await expect(input).toBeDisabled();
      await expect(page.getByRole("heading", { name: "File uploaded", exact: true })).toHaveCount(0);
      release(); await expect(page.getByRole("heading", { name: "File uploaded", exact: true })).toBeVisible();
    } finally { release(); }
    expect(new URL(page.url()).hash).toBe(""); expect(state.calls.filter((item) => item.method === "PUT")).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    const screenshot = testInfo.outputPath(`mcp-upload-confirmed-${width}.png`);
    await page.screenshot({ path: screenshot, fullPage: true, animations: "disabled" });
    await testInfo.attach(`Upload confirmed ${width}px`, { path: screenshot, contentType: "image/png" });
    expect(state.errors).toEqual([]);
  });
}

test("corrupted download never offers saving or sends a delivery receipt", async ({ page }) => {
  const state = await setup(page, false, true);
  await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
  await page.getByRole("button", { name: "Prepare download", exact: true }).click();
  await expect(page.getByRole("region", { name: "MCP file transfer" }).getByRole("alert")).toContainText("does not match");
  await expect(page.getByRole("button", { name: "Save file", exact: true })).toHaveCount(0);
  expect(state.calls.filter((item) => item.method === "POST")).toHaveLength(0);
});

test("expired transfer does not accept files or request content", async ({ page }) => {
  const state = await setup(page, true, false, true);
  await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
  await expect(page.getByRole("heading", { name: "This transfer has expired", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify and upload", exact: true })).toHaveCount(0);
  expect(state.calls.filter((item) => item.path.endsWith("/content"))).toHaveLength(0);
});

test("reload loses the memory-only credential and cannot resume with dashboard cookies", async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
  await expect(page.getByText("Passenger report.pdf", { exact: true })).toBeVisible();
  const count = state.calls.length;
  await page.reload();
  await expect(page.getByRole("heading", { name: "Open the transfer link from your app", exact: true })).toBeVisible();
  expect(state.calls).toHaveLength(count);
  expect(await page.evaluate(() => Object.keys(localStorage).concat(Object.keys(sessionStorage)).some((key) => key.includes("transfer")))).toBe(false);
});

test("filesystem save acknowledges only after the writer closes", async ({ page }) => {
  const state = await setup(page);
  await page.addInitScript(() => {
    Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: async () => ({ createWritable: async () => ({
      write: async () => undefined,
      close: async () => new Promise<void>((resolve) => { (window as Window & { finishPreparedSave?: () => void }).finishPreparedSave = resolve; }),
    }) }) });
  });
  await page.goto(`/mcp/file-transfer/${id}#token=${token}`);
  await page.getByRole("button", { name: "Prepare download", exact: true }).click();
  await page.getByRole("button", { name: "Save file", exact: true }).click();
  await expect(page.getByRole("button", { name: "Save file", exact: true })).toBeDisabled();
  expect(state.calls.filter((item) => item.method === "POST")).toHaveLength(0);
  await page.evaluate(() => (window as Window & { finishPreparedSave?: () => void }).finishPreparedSave?.());
  await expect(page.getByRole("heading", { name: "File saved and confirmed", exact: true })).toBeVisible();
  expect(state.calls.filter((item) => item.method === "POST")).toHaveLength(1);
});
