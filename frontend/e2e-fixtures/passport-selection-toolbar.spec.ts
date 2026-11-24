import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

let runtime = "", styles = "";
test.beforeAll(async () => {
  test.setTimeout(120_000);
  const { build } = await import("vite");
  const bindings = readFileSync(resolve(__dirname, "../features/passports/components/passport-group-bindings.tsx"), "utf8");
  const limits = bindings.match(/export const MAX_(?:BULK_SELECTION|SELECTED_IMAGE_DOWNLOAD) = \d+;/g);
  if (limits?.length !== 2) throw new Error("Actual selection limit declarations are missing");
  const bundled = await build({
    root: resolve(__dirname, ".."), configFile: false, logLevel: "error",
    resolve: { alias: { "@": resolve(__dirname, "..") } },
    define: { "process.env.NODE_ENV": '"production"' },
    plugins: [{ name: "isolated-actual-selection-limits",
      resolveId(source) { return source === "./passport-group-bindings" ? "\0actual-selection-limits" : undefined; },
      load(id) { return id === "\0actual-selection-limits" ? limits.join("\n") : undefined; },
    }],
    build: { write: false, minify: false, cssCodeSplit: false, lib: {
      entry: resolve(__dirname, "support/passport-selection-toolbar-fixture.tsx"),
      formats: ["iife"], name: "PassportSelectionToolbarFixture",
    } },
  });
  const files = (Array.isArray(bundled) ? bundled : [bundled]).flatMap((output) => "output" in output ? output.output : []);
  const code = files.find((output) => output.type === "chunk");
  const css = files.find((output) => output.type === "asset" && output.fileName.endsWith(".css"));
  if (!code || code.type !== "chunk" || !css || css.type !== "asset") throw new Error("Actual toolbar fixture bundle/CSS missing");
  runtime = code.code;
  styles = typeof css.source === "string" ? css.source : new TextDecoder().decode(css.source);
});

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 320, height: 720 }]) {
  test(`bulk action bounds, focus and pointer activation at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const network: string[] = [];
    page.on("request", (request) => network.push(request.url()));
    await page.route("**/*", (route) => route.abort());
    await page.goto("about:blank");
    await page.setContent('<div id="root"></div>');
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: runtime });
    const trigger = page.getByRole("button", { name: "Open bulk actions for 1 selected submissions" });
    await trigger.focus();
    await page.keyboard.press("Enter");
    const popup = page.locator('[aria-label="Bulk submission actions"]');
    await expect(popup).toBeVisible();
    const bounds = await popup.boundingBox();
    if (!bounds) throw new Error("Bulk action popup has no bounds");
    const phase = process.env.PASSPORT_TOOLBAR_BASELINE === "1" ? "before" : "after";
    await page.screenshot({ path: resolve(__dirname, `../../.tmp/ui-pwa-batch/selection-toolbar-${phase}-${viewport.width}.png`), fullPage: true });
    expect(bounds.x).toBeGreaterThanOrEqual(8);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewport.width - 8);
    expect(bounds.y).toBeGreaterThanOrEqual(8);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(viewport.height - 8);
    const exportButton = popup.getByRole("button", { name: "Export Excel (1)" });
    await expect(exportButton).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(popup).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await trigger.click();
    await exportButton.click();
    await expect(page.getByLabel("Synthetic exports")).toHaveText("1");
    await expect(popup).not.toBeVisible();
    await trigger.click();
    await page.getByRole("button", { name: "Outside action" }).click();
    await expect(popup).not.toBeVisible();
    expect(network).toEqual([]);
  });
}
