import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { resolve } from "node:path";

const worker = readFileSync(resolve(__dirname, "../public/sw.js"), "utf8");
const scanner = readFileSync(resolve(__dirname, "../public/offline-scanner.js"), "utf8");
const oldScanner = "/* Synthetic previous cached scanner */";
let server: Server;
let origin: string;
let upgraded = false;
let scannerRequests = 0;

test.beforeAll(async () => {
  server = createServer((request, response) => {
    const path = new URL(request.url!, "http://127.0.0.1").pathname;
    if (path === "/sw.js") {
      response.writeHead(200, { "Content-Type": "application/javascript", "Cache-Control": "no-cache", "Service-Worker-Allowed": "/" });
      response.end(upgraded ? worker : worker.replace("public-static-v12", "public-static-v11"));
    } else if (path === "/offline-scanner.js") {
      scannerRequests++;
      response.writeHead(200, { "Content-Type": "application/javascript", "Cache-Control": "public, max-age=3600" });
      response.end(upgraded ? scanner : oldScanner);
    } else if (path === "/offline/vendor/zxing-browser.min.js") {
      response.writeHead(200, { "Content-Type": "application/javascript" }); response.end("/* Synthetic decoder fixture; no camera invocation. */");
    } else {
      response.writeHead(200, { "Content-Type": "text/html" });
      response.end('<!doctype html><html><body><label>Unsaved note<input id="draft"></label></body></html>');
    }
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
test.afterAll(async () => { await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())); });

test("updates an installed public offline runtime without reloading or clearing pending scans", async ({ page }) => {
  await page.goto(`${origin}/coordinator/update-fixture`);
  await page.evaluate(async () => {
    await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
    await navigator.serviceWorker.ready;
    await new Promise<void>((resolve) => {
      if (navigator.serviceWorker.controller) resolve();
      else navigator.serviceWorker.addEventListener("controllerchange", () => resolve(), { once: true });
    });
  });
  expect(await page.evaluate(async () => (await caches.match("/offline-scanner.js"))!.text())).toBe(oldScanner);
  await page.getByLabel("Unsaved note").fill("Retain this active draft");
  const epoch = await page.evaluate(async () => {
    const documentEpoch = crypto.randomUUID();
    Object.assign(window, { documentEpoch });
    const storageKey = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, storageKey, new TextEncoder().encode("Synthetic retained readiness key"));
    Object.assign(window, { keyProbe: { iv, ciphertext } });
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("passdetection-tour-ops", 5);
      request.onupgradeneeded = () => {
        for (const name of ["pending-attendance-scans", "coordinator-offline-authorizations", "offline-crypto-keys"]) {
          request.result.createObjectStore(name, { keyPath: "id" });
        }
      };
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction(["pending-attendance-scans", "coordinator-offline-authorizations", "offline-crypto-keys"], "readwrite");
        transaction.objectStore("pending-attendance-scans").put({ id: "unsynced-synthetic-scan", ownerUserId: "synthetic-owner", storageVersion: 5 });
        transaction.objectStore("coordinator-offline-authorizations").put({ id: "synthetic-signed-readiness", ownerUserId: "synthetic-owner", trustedHighWaterMs: 12345 });
        transaction.objectStore("offline-crypto-keys").put({ id: "coordinator-offline-aes-gcm-v1", key: storageKey });
        transaction.oncomplete = () => { database.close(); resolve(); };
        transaction.onerror = () => reject(transaction.error);
      };
    });
    localStorage.setItem("passdetection:session-owner", "synthetic-owner");
    return documentEpoch;
  });
  const previousRequests = scannerRequests;
  upgraded = true;
  await page.evaluate(async () => {
    const registration = (await navigator.serviceWorker.getRegistration("/"))!;
    await registration.update();
    registration.waiting?.postMessage({ type: "SKIP_WAITING" });
  });
  await expect.poll(() => page.evaluate(async () => (await caches.keys()).includes("passdetection-public-static-v12"))).toBe(true);
  await expect.poll(() => page.evaluate(async () => (await caches.keys()).includes("passdetection-public-static-v11"))).toBe(false);
  expect(scannerRequests).toBeGreaterThan(previousRequests);
  expect(await page.evaluate(async () => (await caches.match("/offline-scanner.js"))!.text())).toBe(scanner);
  expect(await page.evaluate(() => (window as unknown as { documentEpoch: string }).documentEpoch)).toBe(epoch);
  await expect(page.getByLabel("Unsaved note")).toHaveValue("Retain this active draft");
  expect(await page.evaluate(() => localStorage.getItem("passdetection:session-owner"))).toBe("synthetic-owner");
  expect(await page.evaluate(async () => {
    const cache = await caches.open("passdetection-public-static-v12");
    return (await cache.keys()).map(request => new URL(request.url).pathname).sort();
  })).toEqual(["/offline-scanner.js", "/offline.html", "/offline/vendor/zxing-browser.min.js"]);
  expect(await page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open("passdetection-tour-ops", 5);
    request.onsuccess = () => {
      const database = request.result;
      const row = database.transaction("coordinator-offline-authorizations", "readonly")
        .objectStore("coordinator-offline-authorizations").get("synthetic-signed-readiness");
      row.onsuccess = () => { database.close(); resolve(row.result); };
      row.onerror = () => reject(row.error);
    };
    request.onerror = () => reject(request.error);
  }))).toEqual({ id: "synthetic-signed-readiness", ownerUserId: "synthetic-owner", trustedHighWaterMs: 12345 });
  expect(await page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open("passdetection-tour-ops", 5);
    request.onsuccess = () => {
      const database = request.result;
      const row = database.transaction("offline-crypto-keys", "readonly")
        .objectStore("offline-crypto-keys").get("coordinator-offline-aes-gcm-v1");
      row.onsuccess = () => {
        database.close();
        const { iv, ciphertext } = (window as unknown as { keyProbe: { iv: Uint8Array<ArrayBuffer>; ciphertext: ArrayBuffer } }).keyProbe;
        if (row.result.key.extractable) { reject(new Error("Readiness key became extractable")); return; }
        void crypto.subtle.decrypt({ name: "AES-GCM", iv }, row.result.key, ciphertext)
          .then(bytes => resolve(new TextDecoder().decode(bytes)), reject);
      };
      row.onerror = () => reject(row.error);
    };
    request.onerror = () => reject(request.error);
  }))).toBe("Synthetic retained readiness key");
  expect(await page.evaluate(() => new Promise((resolve, reject) => {
    const request = indexedDB.open("passdetection-tour-ops", 5);
    request.onsuccess = () => {
      const database = request.result;
      const row = database.transaction("pending-attendance-scans", "readonly").objectStore("pending-attendance-scans").get("unsynced-synthetic-scan");
      row.onsuccess = () => { database.close(); resolve(row.result); };
      row.onerror = () => reject(row.error);
    };
    request.onerror = () => reject(request.error);
  }))).toEqual({ id: "unsynced-synthetic-scan", ownerUserId: "synthetic-owner", storageVersion: 5 });
});
