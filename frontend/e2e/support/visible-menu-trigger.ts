import { expect, type Locator } from "@playwright/test";

/** Finish viewport scroll dismissal before opening a menu from its visible anchor. */
export async function prepareVisibleMenuTrigger(trigger: Locator) {
  await trigger.scrollIntoViewIfNeeded();
  await trigger.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  await expect(trigger).toBeInViewport();
}
