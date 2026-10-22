import type { Page } from "@playwright/test";

type Diagnostics = { consoleErrors: string[]; pageErrors: string[]; assetFailures: string[]; assetAborts: string[]; assets: string[]; documentCsp: string };
type CspViolation = { directive: string; blocked: string; sourceFile: string; line: number; column: number; sample: string };
const observations = new WeakMap<Page, Diagnostics>();

export async function observeHologramDiagnostics(page: Page) {
  const diagnostics: Diagnostics = { consoleErrors: [], pageErrors: [], assetFailures: [], assetAborts: [], assets: [], documentCsp: "" };
  observations.set(page, diagnostics);
  page.on("console", (message) => { if (message.type() === "error") diagnostics.consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => diagnostics.pageErrors.push(error.message));
  page.on("requestfailed", (request) => {
    const path = new URL(request.url()).pathname;
    if (!path.startsWith("/ai/test-landscape/") && !path.startsWith("/ai/human-head/")) return;
    const error = request.failure()?.errorText;
    // Retiring a StrictMode or switched-away canvas intentionally cancels loads.
    // Keep these visible in diagnostics; the render tests still require every
    // asset and real textured terrain draws from the surviving canvas.
    (error === "net::ERR_ABORTED" ? diagnostics.assetAborts : diagnostics.assetFailures).push(`${path}: ${error}`);
  });
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (path === "/ai" && response.request().resourceType() === "document") diagnostics.documentCsp = response.headers()["content-security-policy"] ?? "";
    if (!path.startsWith("/ai/test-landscape/") && !path.startsWith("/ai/human-head/")) return;
    if (response.ok()) diagnostics.assets.push(path);
    else diagnostics.assetFailures.push(`${path}: HTTP ${response.status()}`);
  });
  await page.addInitScript(() => {
    const violations: CspViolation[] = [];
    Object.defineProperty(window, "__portraitCspViolations", { value: violations });
    document.addEventListener("securitypolicyviolation", (event) => {
      violations.push({ directive: event.effectiveDirective, blocked: event.blockedURI, sourceFile: event.sourceFile,
        line: event.lineNumber, column: event.columnNumber, sample: event.sample });
    });
  });
}

export async function hologramDiagnostics(page: Page) {
  return { ...observations.get(page), cspViolations: await page.evaluate(() =>
    (window as unknown as { __portraitCspViolations?: CspViolation[] }).__portraitCspViolations ?? []),
  };
}
