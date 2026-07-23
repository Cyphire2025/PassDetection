import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");

const mobileShell = read("./coordinator-mobile-shell.tsx");
const activity = read("./coordinator-group-activity-page.tsx");
const scanner = read("./coordinator-group-scanner.tsx");
const hotel = read("./coordinator-hotel-checkin.tsx");
const passenger = read("./coordinator-passenger-detail-page.tsx");
const globalCss = read("../../../app/globals.css");
const queue = read("../services/attendance-scan-queue.ts");
const progress = read("../services/attendance-session-progress.ts");
const scannerHook = read("../hooks/use-continuous-qr-scanner.ts");
const publicUrl = read("../../../lib/utils/public-url.ts");
const offlinePage = read("../../../public/offline.html");

test("every coordinator login action invokes the safe return-route builder", () => {
  for (const source of [mobileShell, activity, scanner, hotel, passenger]) {
    assert.doesNotMatch(source, /router\.push\(ROUTES\.auth\.coordinatorLogin\s+as never\)/);
  }
  assert.match(mobileShell, /ROUTES\.auth\.coordinatorLogin\(\)/);
  assert.match(activity, /ROUTES\.auth\.coordinatorLogin\(`\/coordinator\/groups\/\$\{groupId\}`\)/);
  assert.match(scanner, /ROUTES\.auth\.coordinatorLogin\(scannerPath\)/);
});

test("large passenger rosters render in bounded progressive chunks", () => {
  assert.match(activity, /const PASSENGER_PAGE_SIZE = 50/);
  assert.match(activity, /passengers\.slice\(0, visibleCount\)/);
  assert.match(activity, /setVisibleCount\(\(current\) => Math\.min\(current \+ PASSENGER_PAGE_SIZE/);
  assert.match(activity, /\[content-visibility:auto\]/);
});

test("attendance completion drains the scan pipeline and sync queue before completion", () => {
  const drainIndex = scanner.indexOf("await scanPipelineRef.current");
  const syncIndex = scanner.indexOf("const syncResult = await syncNow()");
  const completeIndex = scanner.indexOf("await completeMutation.mutateAsync(sessionId)");
  assert.ok(drainIndex >= 0 && drainIndex < syncIndex);
  assert.ok(syncIndex < completeIndex);
  assert.match(scanner, /rejectedCount > 0/);
  assert.match(scanner, /await acknowledgeRejectedScans\(\)/);
});

test("offline scans remain pending until authoritative server reconciliation", () => {
  assert.match(scanner, /Saved offline as pending\. The counted total updates only after server validation\./);
  assert.doesNotMatch(scanner, /const nextCount = .*scannedCountRef/);
  assert.match(queue, /status: response\.status/);
  assert.match(queue, /scannedCount: response\.scanned_count/);
  assert.match(progress, /scanned_count: local\.scanned_count/);
  assert.doesNotMatch(progress, /Math\.max\(session\.scanned_count/);
});

test("hotel scans are serialized and stale hotel responses are ignored", () => {
  assert.match(hotel, /scanPipelineRef\.current = scanPipelineRef\.current/);
  assert.match(hotel, /hotelIdRef\.current !== requestedHotelId/);
  assert.match(hotel, /scanLockedRef\.current = true/);
  assert.match(hotel, /setAwaitingNextPassenger\(true\)/);
  assert.match(hotel, /stopScanner\(\)/);
  assert.match(hotel, /onScanNext=\{scanNextPassenger\}/);
  assert.match(hotel, /Scan next passenger/);
  assert.match(hotel, /aria-live="polite"/);
  assert.match(hotel, /if \(awaitingNextPassenger \|\| !isOnline \|\| devices\.length < 2\) return/);
  assert.match(hotel, /errorMessage && !awaitingNextPassenger/);
  assert.match(hotel, /canAutoResume: \(\) =>/);
  assert.match(scannerHook, /canAutoResumeRef\.current\?\.\(\) \?\? true/);
  assert.match(scannerHook, /addEventListener\("pageshow", resumeScannerIfAllowed\)/);
  assert.match(scannerHook, /removeEventListener\("pageshow", resumeScannerIfAllowed\)/);
  assert.match(hotel, /setHotelsError\(/);
  assert.match(hotel, /setActionError\(/);
});

test("scan frames are constrained by viewport height for short landscape phones", () => {
  assert.match(scanner, /size-\[min\(82vw,20rem,42dvh\)\]/);
  assert.match(hotel, /size-\[min\(66vw,14rem,38dvh\)\]/);
  assert.match(scanner, /data-coordinator-scanner-main/);
  assert.match(globalCss, /@media \(orientation: landscape\) and \(max-height: 500px\)/);
  assert.match(globalCss, /\[data-coordinator-scanner-controls\][\s\S]*max-height: none/);
});

test("attendance scanner auto-start survives a pre-timer effect refresh", () => {
  const timerIndex = scanner.indexOf("const timer = window.setTimeout");
  const lockIndex = scanner.indexOf("autoStartedRef.current = true", timerIndex);
  const startIndex = scanner.indexOf("void startScanner()", timerIndex);
  const callbackEndIndex = scanner.indexOf("}, 150)", timerIndex);

  assert.ok(timerIndex >= 0);
  assert.ok(timerIndex < lockIndex && lockIndex < startIndex && startIndex < callbackEndIndex);
});

test("generated public links use the current production-domain fallback", () => {
  assert.match(publicUrl, /DEFAULT_PUBLIC_APP_URL = "https:\/\/tech\.gctravels\.com"/);
  assert.doesNotMatch(publicUrl, /pass\.cyphire\.in/);
});

test("offline copy does not imply unavailable background synchronization", () => {
  assert.match(offlinePage, /sync after you reconnect and reopen the app/);
  assert.doesNotMatch(offlinePage, /continue syncing when the connection returns/);
});
