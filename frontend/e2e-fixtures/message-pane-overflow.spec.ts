import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

let runtime = "", styles = "";
const phase = process.env.MESSAGE_PANE_BASELINE === "1" ? "before" : "after";
const output = resolve(__dirname, "../../.tmp/message-pane-wrapping");
const panes = ["review", "historical", "document-review", "trip-review", "saved-update", "document-delivery", "inline-preview", "existing-delivery-preview"];
const samples = { small: "Hello,\n\nYour synthetic trip is confirmed.\n\nRegards,\nSynthetic team", long: `Hello,\n\n${"LongSyntheticRecipientName".repeat(7)}\nhttps://travel.example.test/${"synthetic-secure-link-".repeat(12)}\n\nRegards,\nSynthetic team` };
test.beforeAll(async () => {
  test.setTimeout(120_000); await mkdir(output, { recursive: true });
  const { build } = await import("vite");
  const bundles = await build({ root: resolve(__dirname, ".."), configFile: false, logLevel: "error",
    resolve: { alias: { "@": resolve(__dirname, "..") } }, define: { "process.env": '{"NODE_ENV":"production"}' },
    plugins: [{ name: "presentation-only-controller-fixtures", enforce: "pre",
      resolveId(source) { return source === "./use-document-composer" ? "\0fixture-document" : source === "./use-trip-update-composer" ? "\0fixture-trip" : undefined; },
      load(id) { return id === "\0fixture-document" ? "export function useDocumentComposer(){return window.messagePaneModels.document;}" : id === "\0fixture-trip" ? "export function useTripUpdateComposer(){return window.messagePaneModels.trip;}" : undefined; },
    }],
    build: { write: false, minify: false, cssCodeSplit: false, lib: { entry: resolve(__dirname, "support/message-pane-overflow-fixture.tsx"), formats: ["iife"], name: "MessagePaneOverflowFixture" } },
  });
  const files = (Array.isArray(bundles) ? bundles : [bundles]).flatMap(bundle => "output" in bundle ? bundle.output : []);
  const code = files.find(file => file.type === "chunk"), css = files.find(file => file.type === "asset" && file.fileName.endsWith(".css"));
  if (!code || code.type !== "chunk" || !css || css.type !== "asset") throw new Error("Actual component/CSS bundle missing");
  runtime = code.code; styles = typeof css.source === "string" ? css.source : new TextDecoder().decode(css.source);
});
for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 1000 }]) for (const pane of panes) for (const [kind, message] of Object.entries(samples)) {
  test(`${pane} ${kind} inner message bounds at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport); const unexpected: string[] = [], errors: string[] = [];
    page.on("pageerror", error => errors.push(String(error)));
    await page.route("**/*", route => {
      if (route.request().url() === "http://127.0.0.1:3188/message-pane-fixture") return route.fulfill({ contentType: "text/html", body: '<div id="root"></div>' });
      unexpected.push(route.request().url()); return route.abort();
    });
    await page.addInitScript(() => { Object.assign(window, { process: { env: { NODE_ENV: "production" }, browser: true } }); });
    await page.goto("http://127.0.0.1:3188/message-pane-fixture"); await page.addStyleTag({ content: styles });
    await page.evaluate(config => { window.messagePaneFixture = config; }, { pane, message }); await page.addScriptTag({ content: runtime });
    expect(errors, "Presentation fixture must initialize before geometry assertions").toEqual([]);
    if (pane === "saved-update") await page.getByText("View recipient & update details").click();
    const owner = ["review", "historical", "document-review", "trip-review", "document-delivery"].includes(pane) ? page.getByRole("dialog") : page.locator("main");
    const text = owner.locator(".whitespace-pre-wrap, .whitespace-pre-line"); await expect(text).toHaveCount(1);
    await expect(text).toContainText(message);
    const result = await text.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, whiteSpace: getComputedStyle(element).whiteSpace, overflowWrap: getComputedStyle(element).overflowWrap, text: element.textContent, x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width }));
    const outer = await owner.evaluate(element => ({ clientWidth: element.clientWidth, scrollWidth: element.scrollWidth, pageWidth: document.documentElement.scrollWidth, viewport: innerWidth }));
    await writeFile(resolve(output, `${phase}-${pane}-${kind}-${viewport.width}.json`), JSON.stringify({ pane, kind, viewport, result, outer, errors, unexpected }, null, 2));
    expect(errors).toEqual([]); expect(unexpected).toEqual([]); expect(result.text).toContain(message);
    expect(result.whiteSpace).toBe(pane === "document-delivery" ? "pre-line" : "pre-wrap");
    expect(result.scrollWidth, "Actual message text must wrap without a hidden horizontal scroll surface").toBeLessThanOrEqual(result.clientWidth + 1);
    expect(result.x).toBeGreaterThanOrEqual(-1); expect(result.x + result.width).toBeLessThanOrEqual(viewport.width + 1);
    expect(outer.scrollWidth).toBeLessThanOrEqual(outer.clientWidth + 1); expect(outer.pageWidth).toBeLessThanOrEqual(outer.viewport + 1);
    if (kind === "long" && viewport.width === 390) await page.screenshot({ path: resolve(output, `${phase}-${pane}-390.png`), fullPage: true });
  });
}
