import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

let runtime = "", styles = "";
test.beforeAll(async () => {
  const { build } = await import("vite");
  const bundled = await build({
    root: resolve(__dirname, ".."), configFile: false, logLevel: "error",
    resolve: { alias: { "@": resolve(__dirname, "..") } },
    define: { "process.env.NODE_ENV": '"production"' },
    build: { write: false, minify: false, cssCodeSplit: false, lib: {
      entry: resolve(__dirname, "support/replacement-recipient-fixture.tsx"),
      formats: ["iife"], name: "ReplacementRecipientFixture",
    } },
  });
  const outputs = Array.isArray(bundled) ? bundled : [bundled];
  const files = outputs.flatMap((output) => "output" in output ? output.output : []);
  const code = files.find((output) => output.type === "chunk");
  const css = files.find((output) => output.type === "asset" && output.fileName.endsWith(".css"));
  if (!code || code.type !== "chunk" || !css || css.type !== "asset") throw new Error("Replacement browser fixture bundle/CSS missing");
  runtime = code.code;
  styles = typeof css.source === "string" ? css.source : new TextDecoder().decode(css.source);
});

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`native recipient keyboard and long-name layout at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const network: string[] = [];
    page.on("request", (request) => network.push(request.url()));
    await page.route("**/*", (route) => route.abort());
    await page.goto("about:blank");
    await page.setContent('<div id="root"></div>');
    await page.addStyleTag({ content: styles });
    await page.addScriptTag({ content: runtime });
    const choices = page.getByRole("radio");
    await expect(choices).toHaveCount(3);
    await choices.nth(0).focus();
    await page.keyboard.press("ArrowDown");
    await expect(choices.nth(1)).toBeFocused();
    await expect(choices.nth(1)).toBeChecked();
    await expect(page.getByLabel("Selected recipient")).toHaveText("recipient-1");
    const name = page.getByText(/^SYNTHETICLONGNAME/);
    const bounds = await name.evaluate((element) => ({ width: element.clientWidth, contentWidth: element.scrollWidth }));
    await page.screenshot({ path: resolve(__dirname, `../../.tmp/ui-pwa-batch/replacement-${viewport.width}.png`), fullPage: true });
    expect(bounds.contentWidth).toBeLessThanOrEqual(bounds.width + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(network).toEqual([]);
  });
}
