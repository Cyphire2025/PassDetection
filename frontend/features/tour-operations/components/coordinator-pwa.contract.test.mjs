import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), "utf8");
const readBytes = (relativePath) => readFileSync(new URL(relativePath, import.meta.url));

const mobileShell = read("./coordinator-mobile-shell.tsx");
const activity = read("./coordinator-group-activity-page.tsx");
const officeAttendance = read("../../operations/components/tour-group-attendance-page.tsx");
const scanner = read("./coordinator-group-scanner.tsx");
const hotel = read("./coordinator-hotel-checkin.tsx");
const passenger = read("./coordinator-passenger-detail-page.tsx");
const globalDrain = read("./coordinator-offline-scan-drain.tsx");
const coordinatorLayout = read("../../../app/coordinator/layout.tsx");
const dashboardLayout = read("../../../app/(dashboard)/layout.tsx");
const globalCss = read("../../../app/globals.css");
const queue = read("../services/attendance-scan-queue.ts");
const batchPolicy = read("../services/attendance-batch-policy.ts");
const offlineAuthorization = read("../services/browser-offline-authorization.ts");
const offlineCrypto = read("../services/browser-offline-crypto.ts");
const offlineDatabase = read("../services/browser-offline-database.ts");
const offlineSnapshot = read("../services/offline-snapshot.ts");
const progress = read("../services/attendance-session-progress.ts");
const closeoutCheckpoint = read("../services/attendance-closeout-checkpoint.ts");
const closeoutReporting = read("../hooks/use-attendance-closeout-reporting.ts");
const operationsHooks = read("../../operations/hooks/use-operations.ts");
const operationsApi = read("../../operations/api/operations.api.ts");
const dashboardRealtimeBridge = read("../../operations/components/dashboard-realtime-attendance-bridge.tsx");
const dashboardRealtimeProtocol = read("../../operations/services/dashboard-realtime.ts");
const scannerHook = read("../hooks/use-continuous-qr-scanner.ts");
const apiEndpoints = read("../../../lib/api/endpoints.ts");
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

test("finishing coordinator scanning is local-only and preserves queued reconciliation", () => {
  const drainIndex = scanner.indexOf("await scanPipelineRef.current");
  const syncIndex = scanner.indexOf("await syncNow()");
  const exitIndex = scanner.indexOf("router.replace(`/coordinator/groups/${groupId}`");
  assert.ok(drainIndex >= 0 && drainIndex < syncIndex);
  assert.ok(syncIndex < exitIndex);
  assert.match(scanner, /This only exits your scanner\. The shared activity stays open for other coordinators/);
  assert.match(scanner, /Promise\.allSettled/);
  assert.match(scanner, /Finish my scanning/);
  assert.doesNotMatch(scanner, /completeMutation|useCompleteMyAttendanceSession/);
  assert.doesNotMatch(operationsHooks, /useCompleteMyAttendanceSession/);
  assert.doesNotMatch(operationsApi, /completeMyAttendanceSession/);
  assert.doesNotMatch(apiEndpoints, /mySessionComplete/);
});

test("office global close is manager-only and refreshes authoritative checkpoint evidence first", () => {
  const refreshIndex = officeAttendance.indexOf("refreshed = await refetch()");
  const closeIndex = officeAttendance.indexOf("await closeMutation.mutateAsync");
  assert.ok(refreshIndex >= 0 && refreshIndex < closeIndex);
  assert.match(officeAttendance, /role === "super_admin"/);
  assert.match(officeAttendance, /role === "agency_admin"/);
  assert.match(officeAttendance, /role === "agency_manager"/);
  assert.match(officeAttendance, /Coordinator checkpoints clear/);
  assert.match(officeAttendance, /managedAttendanceCloseoutStatus|session\.closeout/);
  assert.match(officeAttendance, /do not include passenger names, QR values, passport details/);
  assert.doesNotMatch(officeAttendance, /Fleet closeout|all devices clear|fleet proven/i);
  assert.match(officeAttendance, /Close after clear checkpoints/);
  assert.match(officeAttendance, /was closed, but the latest status could not be loaded/);
  assert.match(operationsHooks, /useCompleteManagedAttendanceSession/);
  assert.match(operationsApi, /completeManagedAttendanceSession/);
  assert.match(apiEndpoints, /managedSessionComplete/);
});

test("browser closeout reports are count-only, account-fenced, coalesced, and cross-tab serialized", () => {
  assert.match(closeoutCheckpoint, /sessionVersion/);
  assert.match(closeoutCheckpoint, /userId/);
  assert.match(closeoutCheckpoint, /assertBrowserAuthenticationSnapshotCurrent/);
  assert.match(closeoutCheckpoint, /publisherLanes/);
  assert.match(closeoutCheckpoint, /activeLane\.pending\.request = request/);
  assert.match(closeoutCheckpoint, /navigator\.locks\.request/);
  assert.match(closeoutCheckpoint, /collectCheckpointForAuthentication/);
  assert.match(closeoutCheckpoint, /collectBrowserAttendanceQueueCloseout/);
  assert.match(queue, /assertAuthenticationSnapshotCurrent\(authentication\)/);
  assert.match(queue, /row\.ownerUserId !== authentication\.userId/);
  assert.match(closeoutReporting, /CHECKPOINT_REFRESH_MS = 30_000/);
  assert.match(closeoutReporting, /document\.visibilityState !== "visible"/);
  for (const approved of [
    "pending_count",
    "sending_count",
    "retryable_count",
    "needs_review_count",
    "unreviewed_rejected_count",
    "oldest_pending_age_seconds",
  ]) {
    assert.match(closeoutCheckpoint, new RegExp(`\\b${approved}\\b`));
  }
  assert.doesNotMatch(
    closeoutCheckpoint,
    /checkpoint\s*=\s*\{[\s\S]*?(passenger|qr_payload|client_event|device_id)/i,
  );
  assert.match(closeoutCheckpoint, /pending_count: queue\.pending/);
  assert.match(closeoutCheckpoint, /sending_count: queue\.sending/);
  assert.match(closeoutCheckpoint, /retryable_count: queue\.retryable/);
  assert.doesNotMatch(closeoutCheckpoint, /sending_count: 0|retryable_count: 0/);
  assert.match(queue, /deliveryState: "sending"/);
  assert.match(queue, /row\.deliveryState === "sending"/);
  assert.match(queue, /publishBrowserAttendanceQueueCloseout<T>[\s\S]*?withOwnerQueueLock\(authentication\.userId[\s\S]*?await publish\(queue\)/);
  assert.match(closeoutCheckpoint, /publishBrowserAttendanceQueueCloseout\([\s\S]*?publish: async \(queue\)[\s\S]*?operationsApi\.publishMyAttendanceCloseoutCheckpoint/);
  const drainIndex = queue.indexOf("async function performPendingAttendanceScanSync");
  const claimIndex = queue.indexOf("claimPendingAttendanceDelivery", drainIndex);
  const networkIndex = queue.indexOf("operationsApi.scanMyAttendanceSession", claimIndex);
  assert.ok(drainIndex >= 0 && drainIndex < claimIndex && claimIndex < networkIndex);
});

test("durable browser enqueues trigger an immediate best-effort closeout recomputation", () => {
  const captureIndex = scanner.indexOf("const authentication = useAuthStore.getState()");
  const recordIndex = scanner.indexOf("const result = await recordScan(scan)");
  const publishIndex = scanner.indexOf(
    "publishBrowserAttendanceCloseoutCheckpoint(groupId, sessionId)",
    recordIndex,
  );
  const mountedIndex = scanner.indexOf("if (!mountedRef.current) return", recordIndex);
  assert.ok(captureIndex >= 0 && captureIndex < recordIndex);
  assert.ok(recordIndex < publishIndex);
  assert.ok(publishIndex < mountedIndex);
  assert.match(scanner, /if \(result\.mode === "queued"\)/);
  assert.match(scanner, /result\.pending\.ownerUserId === capturedOwnerUserId/);
  assert.match(scanner, /currentAuthentication\.sessionVersion === capturedSessionVersion/);
  assert.match(scanner, /publishBrowserAttendanceCloseoutCheckpoint[\s\S]*?\.catch\(\(\) => undefined\)/);
  const durablePutIndex = queue.indexOf("store.put(storedPendingScan)");
  const scheduleIndex = queue.indexOf("announceScheduleChanged()", durablePutIndex);
  assert.ok(durablePutIndex >= 0 && durablePutIndex < scheduleIndex);
  assert.match(queue, /collectBrowserAttendanceQueueCloseout[\s\S]*?withOwnerQueueLock/);
});

test("managers create canonical activities while coordinators remain selection-only", () => {
  assert.match(officeAttendance, /Prepare attendance activity/);
  assert.match(officeAttendance, /useCreateManagedAttendanceSession/);
  assert.match(officeAttendance, /Create the canonical name and UUID before coordinators scan/);
  assert.match(operationsHooks, /useCreateManagedAttendanceSession/);
  assert.match(operationsApi, /createManagedAttendanceSession/);
  assert.match(apiEndpoints, /managedSessions/);
  assert.match(activity, /Select a centrally prepared activity/);
  assert.match(activity, /Ask a manager to create one/);
  assert.doesNotMatch(activity, /ActivityStarter|coordinator-activity-name|Start Scanner/);
  assert.doesNotMatch(operationsHooks, /useCreateMyAttendanceSession/);
  assert.doesNotMatch(operationsApi, /createMyAttendanceSession/);
});

test("office attendance uses targeted invalidation with bounded repair polling", () => {
  assert.match(operationsHooks, /subscribeAttendanceInvalidationHints/);
  assert.match(operationsHooks, /attendanceRepairIntervalMs/);
  assert.match(operationsHooks, /refetchIntervalInBackground: false/);
  assert.match(operationsHooks, /refetchOnReconnect: "always"/);
  assert.match(operationsHooks, /refetchOnWindowFocus: "always"/);
  assert.match(officeAttendance, /Targeted updates with 5–7 second repair/);
  assert.match(officeAttendance, /Targeted updates with 30–40 second repair/);
});

test("bounded coordinator summaries and cookie-auth hints retain authoritative repair", () => {
  assert.match(operationsApi, /coordinators_truncated/);
  assert.match(operationsApi, /checkpoint_state/);
  assert.match(officeAttendance, /session\.coordinators\.map/);
  assert.match(officeAttendance, /coordinator\.scanned_count/);
  assert.match(dashboardLayout, /DashboardRealtimeAttendanceBridge/);
  assert.match(coordinatorLayout, /DashboardRealtimeAttendanceBridge/);
  assert.match(apiEndpoints, /realtime: "\/api\/v1\/dashboard\/realtime"/);
  assert.match(dashboardRealtimeProtocol, /API_ENDPOINTS\.dashboard\.realtime/);
  assert.match(dashboardRealtimeBridge, /\{\"type\":\"heartbeat_ack\"\}/);
  assert.match(dashboardRealtimeBridge, /source: "server-push"/);
  assert.match(dashboardRealtimeBridge, /latestCursorByGroup/);
  assert.doesNotMatch(dashboardRealtimeBridge, /Authorization|access_token|searchParams|query_params/);
  assert.match(operationsHooks, /previous: queryClient\.getQueryData<GroupAttendanceSummary>/);
  assert.match(operationsHooks, /refetchInterval:/);
});

test("offline scans remain pending until authoritative server reconciliation", () => {
  assert.match(scanner, /Saved offline as pending\. The counted total updates only after server validation\./);
  assert.doesNotMatch(scanner, /const nextCount = .*scannedCountRef/);
  assert.match(queue, /status: response\.status/);
  assert.match(queue, /scannedCount: response\.scanned_count/);
  assert.match(progress, /Math\.max\(session\.scanned_count, local\.scanned_count\)/);
  assert.match(queue, /groupId: string/);
  assert.match(queue, /createAttendanceScanReference/);
  assert.match(queue, /attendanceQueueRowId\(scanReference\)/);
  assert.doesNotMatch(queue, /return `\$\{ownerUserId\}:\$\{groupId\}:\$\{sessionId\}:\$\{qrPayload\}`/);
  assert.match(progress, /:group:\$\{groupId\}/);
  assert.match(offlineDatabase, /BROWSER_OFFLINE_DB_VERSION = 5/);
  assert.match(queue, /protectPendingAttendanceScan/);
  assert.match(queue, /protectedQrPayload/);
  assert.match(queue, /migrateLegacyQueueRecords/);
  assert.match(queue, /Invalid, corrupt, or unattributable legacy rows remain quarantined/);
  assert.match(
    queue,
    /removePendingAttendanceScan[\s\S]*?DISCARD_TOMBSTONE_STORE[\s\S]*?add\(createDiscardTombstone\(row, reasonCategory\)\)[\s\S]*?pendingStore\.delete\(id\)/,
  );
});

test("connected coordinator devices converge through invalidation and conditional repair", () => {
  assert.match(coordinatorLayout, /DashboardRealtimeAttendanceBridge/);
  assert.match(operationsHooks, /publishAttendanceInvalidationHint/);
  assert.match(operationsHooks, /attendanceRepairIntervalMs/);
  assert.match(scanner, /reconcileLiveAttendanceCount/);
  assert.match(scanner, /liveScannedCount/);
});

test("compatible offline scans replay through bounded session batches", () => {
  assert.match(queue, /scanMyAttendanceSessionBatch/);
  assert.match(queue, /\.slice\(0, 50\)/);
  assert.match(batchPolicy, /item\.retryable === false/);
  assert.match(queue, /markPendingAttendanceRetry/);
  assert.match(queue, /ATTENDANCE_SCAN_BATCH_INVALID_RESPONSE/);
  assert.match(queue, /isBatchCompatiblePendingScan/);
  assert.match(apiEndpoints, /mySessionScanBatch/);
  assert.match(operationsApi, /batch_id: batchId/);
  assert.match(operationsApi, /client_event_id: scan\.clientEventId/);
});

test("offline queue bounds storage and encrypts passenger recovery labels", () => {
  assert.match(queue, /MAX_PENDING_ATTENDANCE_SCANS_PER_OWNER = 5_000/);
  assert.match(queue, /store\.index\(OWNER_INDEX\)\.count\(ownerUserId\)/);
  assert.match(queue, /AttendanceQueueCapacityError/);
  assert.match(queue, /protectBrowserJson\([\s\S]*?\{ qrPayload, \.\.\.\(recovery \? \{ recovery \} : \{\}\) \}/);
  assert.match(queue, /protectRejectedAttendanceScan/);
  assert.match(queue, /protectedRecovery/);
  assert.match(offlineScanner, /MAX_PENDING_SCANS_PER_OWNER = 5000/);
});

test("delayed offline writes cannot recreate a previous account after cleanup", () => {
  assert.match(offlineSnapshot, /snapshotIdentityIsCurrent\(identity\)/);
  assert.match(offlineSnapshot, /sessionVersion/);
  assert.match(offlineSnapshot, /cleanupTransaction[\s\S]*?delete\(record\.id\)/);
  assert.match(offlineAuthorization, /assertCoordinatorIdentityIsCurrent\(identity\)/);
  assert.match(offlineAuthorization, /sessionVersion/);
  assert.match(offlineAuthorization, /cleanupTransaction[\s\S]*?delete\(record\.id\)/);
  assert.match(queue, /assertCurrentOwner\(ownerUserId\)/);
});

test("the coordinator shell replays saved scans after leaving the scanner route", () => {
  assert.match(coordinatorLayout, /<CoordinatorOfflineScanDrain \/>/);
  assert.match(globalDrain, /getNextPendingAttendanceAttemptAt\(\)/);
  assert.match(globalDrain, /syncPendingAttendanceScans\(\)/);
  assert.match(globalDrain, /addEventListener\("online", handleReconnect\)/);
  assert.match(globalDrain, /addEventListener\("pageshow", handleReconnect\)/);
  assert.match(globalDrain, /subscribeAttendanceQueueScheduleChanges/);
  assert.doesNotMatch(globalDrain, /setInterval|RETRY_INTERVAL_MS/);
  assert.match(queue, /let activeSync:/);
});

test("offline replay stops after the first recoverable failure", () => {
  assert.match(queue, /markPendingAttendanceRetry[\s\S]*?failed \+= 1;[\s\S]*?stop = true/);
  assert.match(queue, /stop: !permanent/);
  assert.match(queue, /if \(chunkResult\.stop\) break/);
});

test("offline replay quarantines every non-counting HTTP 200 response", () => {
  assert.match(queue, /disposition === "terminal-rejection"[\s\S]*?quarantineRejectedAttendanceScan/);
  assert.match(
    queue,
    /isSuccessfulAttendanceReplayStatus\(response\.status\)[\s\S]*?removePendingForOwner[\s\S]*?: quarantineRejectedAttendanceScan/,
  );
});

test("manager completion stops fresh capture while preserving queued reconciliation", () => {
  assert.match(scanner, /if \(isFinishing \|\| isSessionCompleted\) return/);
  assert.match(scanner, /if \(isSessionCompleted\) stopScanner\(\)/);
  assert.match(scanner, /New camera scans are stopped/);
  assert.match(scanner, /Scans saved before closure continue synchronizing/);
  assert.match(queue, /syncSource: "offline"/);
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
  assert.doesNotMatch(offlineScanner, /GROUPS_SNAPSHOT_KEY|SESSIONS_SNAPSHOT_KEY/);
  assert.match(offlineScanner, /readAuthorizedCoordinatorSelections/);
  assert.match(offlineScanner, /subtle\.verify/);
  assert.match(offlineScanner, /authorizeDecodedScan/);
  assert.match(offlineScanner, /token_hash === tokenHash/);
  assert.match(offlineScanner, /resolveAuthorizationTrustedTime/);
  assert.match(offlineScanner, /const DB_NAME = "passdetection-tour-ops"/);
  assert.match(offlineScanner, /const DB_VERSION = 5/);
  assert.match(offlineScanner, /const PENDING_STORE_NAME = "pending-attendance-scans"/);
  assert.match(offlineScanner, /\/\^pdatt:\[A-Za-z0-9_-\]\{43\}\$\//);
  assert.match(offlineScanner, /createScanReference\(selection\)/);
  assert.match(offlineScanner, /`attendance-scan:\$\{scanReference\}`/);
  assert.doesNotMatch(offlineScanner, /`\$\{selection\.ownerUserId\}:\$\{selection\.groupId\}:\$\{selection\.sessionId\}:\$\{selection\.qrPayload\}`/);
  for (const field of [
    "groupId",
    "sessionId",
    "clientEventId",
    "scannedAt",
    "deviceId",
    "id",
    "ownerUserId",
    "queuedAt",
    "scanReference",
    "attemptCount",
    "nextAttemptAt",
  ]) {
    assert.match(offlineScanner, new RegExp(`\\b${field}\\b`));
  }
  assert.match(offlineScanner, /protectedQrPayload/);
  assert.match(offlineScanner, /storageVersion: 5/);
  assert.match(offlineScanner, /AES-GCM/);
  assert.match(offlineAuthorization, /Ed25519/);
  assert.match(offlineAuthorization, /CLOCK_ROLLBACK/);
  assert.match(offlineAuthorization, /QR_NOT_IN_ACTIVE_ROSTER/);
  const runtimeRegistrationIndex = offlineAuthorization.indexOf(
    '"/api/v1/tour-operations/coordinator/attendance/runtime"',
  );
  const authorizationFetchIndex = offlineAuthorization.indexOf(
    '/offline-authorization`',
  );
  assert.ok(runtimeRegistrationIndex >= 0 && runtimeRegistrationIndex < authorizationFetchIndex);
  assert.match(offlineAuthorization, /runtime_id: UUID/);
  assert.match(offlineAuthorization, /HttpOnly cookie set by the server is authoritative/);
  assert.match(offlineScanner, /deviceId: authorization\.runtimeId/);
  assert.match(offlineScanner, /runtimeId: authorization\.runtimeId/);
  assert.match(queue, /runtimeId: authorization\.runtimeId/);
  assert.match(queue, /runtimeId: scan\.runtimeId/);
  assert.match(operationsApi, /runtime_id: runtimeId/);
  assert.doesNotMatch(offlineScanner, /DEVICE_ID_KEY|localStorage\.setItem\([^)]*device/i);
  assert.match(offlineCrypto, /extractable/);
  assert.match(offlineSnapshot, /minimizeOfflineSnapshotForStorage/);
  assert.doesNotMatch(offlineSnapshot, /localStorage\.setItem/);
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
  assert.match(globalDrain, /syncAttendanceDiscardTombstones/);
  assert.match(globalDrain, /Promise\.allSettled/);
});

test("service worker caches only the exact public offline runtime and safely re-warms it", () => {
  assert.match(serviceWorker, /passdetection-public-static-v10/);
  assert.match(
    serviceWorker,
    /const PUBLIC_STATIC_ASSETS = \[\s*"\/offline\.html",\s*"\/offline-scanner\.js",\s*"\/offline\/vendor\/zxing-browser\.min\.js",\s*\]/,
  );
  assert.doesNotMatch(serviceWorker, /manifest\.webmanifest/);
  assert.doesNotMatch(serviceWorker, /pwa-icon|apple-touch-icon/);
  assert.doesNotMatch(serviceWorker, /cache\.put\(/);
  assert.match(serviceWorker, /COORDINATOR_PATH_PATTERN\.test\(url\.pathname\)/);
  assert.match(
    serviceWorker,
    /event\.request\.mode === "navigate"[\s\S]*?&& COORDINATOR_PATH_PATTERN\.test\(url\.pathname\)/,
  );
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
