import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");
const readBytes = (relativePath) => readFileSync(new URL(relativePath, import.meta.url));

const mobileShell = read("./coordinator-mobile-shell.tsx");
const activity = read("./coordinator-group-activity-page.tsx");
const scanner = read("./coordinator-group-scanner.tsx");
const hotel = read("./coordinator-hotel-checkin.tsx");
const passenger = read("./coordinator-passenger-detail-page.tsx");
const globalDrain = read("./coordinator-offline-scan-drain.tsx");
const coordinatorLayout = read("../../../app/coordinator/layout.tsx");
const globalCss = read("../../../app/globals.css");
const queue = read("../services/attendance-scan-queue.ts");
const progress = read("../services/attendance-session-progress.ts");
const operationsHooks = read("../../operations/hooks/use-operations.ts");
const scannerHook = read("../hooks/use-continuous-qr-scanner.ts");
const publicUrl = read("../../../lib/utils/public-url.ts");
const offlinePage = read("../../../public/offline.html");
const offlineScanner = read("../../../public/offline-scanner.js");
const serviceWorker = read("../../../public/sw.js");
const zxingLicense = read("../../../public/offline/vendor/zxing-browser.LICENSE.txt");
const zxingVendor = readBytes("../../../public/offline/vendor/zxing-browser.min.js");

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
  assert.match(progress, /Math\.max\(session\.scanned_count, local\.scanned_count\)/);
  assert.match(queue, /groupId: string/);
  assert.match(queue, /\$\{ownerUserId\}:\$\{groupId\}:\$\{sessionId\}:\$\{qrPayload\}/);
  assert.match(progress, /:group:\$\{groupId\}/);
  assert.match(queue, /const DB_VERSION = 3/);
  assert.doesNotMatch(queue, /event\.oldVersion < 4/);
});

test("connected coordinator devices refresh shared activity counts within two seconds", () => {
  assert.match(operationsHooks, /refetchInterval: 1_500/);
  assert.match(scanner, /reconcileLiveAttendanceCount/);
  assert.match(scanner, /liveScannedCount/);
});

test("the coordinator shell replays saved scans after leaving the scanner route", () => {
  assert.match(coordinatorLayout, /<CoordinatorOfflineScanDrain \/>/);
  assert.match(globalDrain, /countPendingAttendanceScans\(\)/);
  assert.match(globalDrain, /syncPendingAttendanceScans\(\)/);
  assert.match(globalDrain, /addEventListener\("online", handleReconnect\)/);
  assert.match(globalDrain, /addEventListener\("pageshow", handleReconnect\)/);
  assert.match(globalDrain, /RETRY_INTERVAL_MS = 15_000/);
  assert.match(queue, /let activeSyncPromise/);
});

test("offline replay stops after the first recoverable failure", () => {
  assert.match(
    queue,
    /else \{\s*failed \+= 1;[\s\S]*?Preserve the queue and stop this drain[\s\S]*?break;\s*\}/,
  );
});

test("offline replay quarantines every non-counting HTTP 200 response", () => {
  assert.match(
    queue,
    /if \(!isSuccessfulAttendanceReplayStatus\(response\.status\)\) \{[\s\S]*?await quarantineRejectedAttendanceScan\([\s\S]*?discarded \+= 1;[\s\S]*?continue;/,
  );
});

test("one coordinator completing a shared activity cannot block other scanners", () => {
  assert.doesNotMatch(
    scanner,
    /useEffect\(\(\) => \{\s*if \(isCompleting \|\| isSessionCompleted\) return/,
  );
  assert.doesNotMatch(scanner, /if \(isSessionCompleted\) stopScanner\(\)/);
  assert.match(scanner, /Completed - late scans remain open/);
  assert.match(activity, /router\.push\(`\/coordinator\/groups\/\$\{groupId\}\/scanner\?sessionId=\$\{session\.id\}`/);
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

test("cold-offline coordinator shell queues only owner-scoped attendance scans", () => {
  assert.match(offlinePage, /Offline attendance scanner/);
  assert.match(offlinePage, /id="group-select"/);
  assert.match(offlinePage, /id="session-select"/);
  assert.match(offlinePage, /id="pending-count"/);
  assert.match(offlinePage, /\/offline\/vendor\/zxing-browser\.min\.js/);
  assert.match(offlinePage, /\/offline-scanner\.js/);
  assert.match(offlineScanner, /const SESSION_OWNER_KEY = "passdetection:session-owner"/);
  assert.match(
    offlineScanner,
    /`\$\{GROUPS_SNAPSHOT_KEY\}:user:\$\{ownerId\}`/,
  );
  assert.match(
    offlineScanner,
    /`\$\{SESSIONS_SNAPSHOT_KEY\}:\$\{groupId\}:user:\$\{ownerId\}`/,
  );
  assert.match(offlineScanner, /const DB_NAME = "passdetection-tour-ops"/);
  assert.match(offlineScanner, /const DB_VERSION = 3/);
  assert.match(offlineScanner, /const PENDING_STORE_NAME = "pending-attendance-scans"/);
  assert.match(offlineScanner, /\/\^pdatt:\[A-Za-z0-9_-\]\{43\}\$\//);
  assert.match(
    offlineScanner,
    /`\$\{selection\.ownerUserId\}:\$\{selection\.groupId\}:\$\{selection\.sessionId\}:\$\{selection\.qrPayload\}`/,
  );
  for (const field of [
    "groupId",
    "sessionId",
    "qrPayload",
    "clientEventId",
    "scannedAt",
    "deviceId",
    "id",
    "ownerUserId",
    "queuedAt",
  ]) {
    assert.match(offlineScanner, new RegExp(`\\b${field}\\b`));
  }
  assert.doesNotMatch(offlineScanner, /\bfetch\s*\(/);
  assert.doesNotMatch(offlineScanner, /new\s+XMLHttpRequest/);
  assert.doesNotMatch(offlineScanner, /new\s+WebSocket/);
  assert.doesNotMatch(offlineScanner, /navigator\.sendBeacon/);
  assert.match(offlineScanner, /document\.addEventListener\("visibilitychange"/);
  assert.match(offlineScanner, /window\.addEventListener\("pagehide"/);
  assert.match(offlineScanner, /window\.addEventListener\("online"/);
  const reconnectHandler = offlineScanner.indexOf("function handleOnline()");
  const reconnectPipeline = offlineScanner.indexOf("void scanPipeline", reconnectHandler);
  const reconnectRedirect = offlineScanner.indexOf(
    "window.location.replace(coordinatorUrl)",
    reconnectHandler,
  );
  assert.ok(
    reconnectHandler >= 0
      && reconnectPipeline > reconnectHandler
      && reconnectRedirect > reconnectPipeline,
  );
  assert.match(offlineScanner, /readCurrentOwner\(\) !== ownerUserId/);
  assert.match(offlineScanner, /window\.location\.replace\(coordinatorUrl\)/);
});

test("service worker caches only the exact public offline runtime and safely re-warms it", () => {
  assert.match(serviceWorker, /passdetection-public-static-v8/);
  assert.match(
    serviceWorker,
    /const PUBLIC_STATIC_ASSETS = \[\s*"\/offline\.html",\s*"\/offline-scanner\.js",\s*"\/offline\/vendor\/zxing-browser\.min\.js",\s*\]/,
  );
  assert.doesNotMatch(serviceWorker, /manifest\.webmanifest/);
  assert.doesNotMatch(serviceWorker, /pwa-icon|apple-touch-icon/);
  assert.doesNotMatch(serviceWorker, /cache\.put\(/);
  assert.match(serviceWorker, /COORDINATOR_PATH_PATTERN\.test\(url\.pathname\)/);
  assert.match(serviceWorker, /response\.ok \? warmOfflineShell\(\)/);
  assert.match(
    serviceWorker,
    /COORDINATOR_PATH_PATTERN\.test\(url\.pathname\)[\s\S]*?response\.status >= 500[\s\S]*?caches\.match\("\/offline\.html"\)/,
  );
  assert.match(serviceWorker, /event\.request\.destination === ""/);
  assert.match(serviceWorker, /event\.respondWith\(coordinatorResponse\)/);
  assert.match(serviceWorker, /cached \?\? fetch\(event\.request\)/);
  assert.match(serviceWorker, /event\.waitUntil\(removeRetiredAppCaches\(\)\)/);
});

test("offline QR decoder is the pinned MIT-licensed @zxing/browser distribution", () => {
  assert.match(zxingLicense, /MIT License/);
  assert.match(offlineScanner, /@zxing\/browser 0\.2\.0 UMD distribution/);
  assert.equal(
    createHash("sha256").update(zxingVendor).digest("hex"),
    "066bc34edfcdd4a33f0964aeec967752a0dea1ccaf36e58e319ac9fcb5070f6a",
  );
});
