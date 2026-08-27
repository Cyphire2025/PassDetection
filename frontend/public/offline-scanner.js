/*
 * Standalone cold-offline coordinator attendance scanner.
 *
 * QR decoding uses the exact @zxing/browser 0.2.0 UMD distribution vendored at
 * /offline/vendor/zxing-browser.min.js. It is MIT licensed; the upstream
 * license is preserved at /offline/vendor/zxing-browser.LICENSE.txt.
 *
 * This file deliberately contains no fetch, XMLHttpRequest, WebSocket, or
 * beacon path. It can only read validated, owner-scoped cached snapshots and
 * append scans to the existing owner-scoped IndexedDB queue.
 */
(function offlineCoordinatorScanner() {
  "use strict";

  const SESSION_OWNER_KEY = "passdetection:session-owner";
  const DB_NAME = "passdetection-tour-ops";
  const DB_VERSION = 5;
  const PENDING_STORE_NAME = "pending-attendance-scans";
  const REJECTED_STORE_NAME = "rejected-attendance-scans";
  const OWNER_INDEX = "owner-user-id";
  const AUTHORIZATION_STORE_NAME = "coordinator-offline-authorizations";
  const SNAPSHOT_STORE_NAME = "coordinator-offline-snapshots";
  const DISCARD_STORE_NAME = "attendance-discard-tombstones";
  const CRYPTO_KEY_STORE_NAME = "offline-crypto-keys";
  const STORAGE_KEY_ID = "coordinator-offline-aes-gcm-v1";
  const MAX_PENDING_SCANS_PER_OWNER = 5000;
  const QR_PAYLOAD_PATTERN = /^pdatt:[A-Za-z0-9_-]{43}$/;
  const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const COORDINATOR_PATH_PATTERN = /^\/coordinator(?:\/|$)/;
  const SCANNER_PATH_PATTERN =
    /^\/coordinator\/groups\/([0-9a-f-]{36})(?:\/scanner)?(?:\/|$)/i;

  const elements = {
    generic: document.getElementById("generic-offline"),
    unavailable: document.getElementById("offline-unavailable"),
    unavailableTitle: document.getElementById("offline-unavailable-title"),
    unavailableMessage: document.getElementById("offline-unavailable-message"),
    scanner: document.getElementById("offline-scanner"),
    onlineBanner: document.getElementById("online-banner"),
    onlineReturnLink: document.getElementById("online-return-link"),
    groupSelect: document.getElementById("group-select"),
    sessionSelect: document.getElementById("session-select"),
    selectedActivity: document.getElementById("selected-activity"),
    pendingCount: document.getElementById("pending-count"),
    preview: document.getElementById("camera-preview"),
    placeholder: document.getElementById("camera-placeholder"),
    startButton: document.getElementById("start-camera"),
    stopButton: document.getElementById("stop-camera"),
    feedback: document.getElementById("scan-feedback"),
  };

  let ownerUserId = null;
  let cachedGroups = [];
  let sessionsByGroup = new Map();
  let scannerControls = null;
  let codeReader = null;
  let cameraStarting = false;
  let cameraGeneration = 0;
  let scanPipeline = Promise.resolve();
  let lastDecodedPayload = "";
  let lastDecodedAt = 0;
  let reconnectInProgress = false;
  let privacyMigrationPromise = null;
  let authorizationByGroup = new Map();

  void initialize();

  async function initialize() {
    if (!COORDINATOR_PATH_PATTERN.test(window.location.pathname)) return;

    ownerUserId = readCurrentOwner();
    if (!ownerUserId) {
      showUnavailable(
        "Offline scanner unavailable",
        "No valid signed-in coordinator snapshot is available. Reconnect and sign in again.",
      );
      return;
    }

    const requested = readRequestedSelection();
    let snapshot;
    try {
      snapshot = await readAuthorizedCoordinatorSelections(ownerUserId, requested.groupId);
    } catch {
      showUnavailable(
        "Signed offline readiness unavailable",
        "Reconnect and open this activity online to verify its signed roster and schedule.",
      );
      return;
    }
    cachedGroups = snapshot.groups;
    sessionsByGroup = snapshot.sessionsByGroup;

    if (cachedGroups.length === 0) {
      showUnavailable(
        "No cached groups",
        "Reconnect and open an assigned coordinator group once before scanning offline.",
      );
      return;
    }

    const groupsWithSessions = cachedGroups.filter(
      (group) => (sessionsByGroup.get(group.id) ?? []).length > 0,
    );
    if (groupsWithSessions.length === 0) {
      showUnavailable(
        "No cached activities",
        "Reconnect and open an attendance activity once before scanning offline.",
      );
      return;
    }

    cachedGroups = groupsWithSessions;
    populateGroupOptions(requested.groupId);
    populateSessionOptions(requested.sessionId);
    elements.generic.hidden = true;
    elements.unavailable.hidden = true;
    elements.scanner.hidden = false;
    elements.groupSelect.addEventListener("change", handleGroupChange);
    elements.sessionSelect.addEventListener("change", handleSessionChange);
    elements.startButton.addEventListener("click", startCamera);
    elements.stopButton.addEventListener("click", () => stopCamera("Camera stopped."));
    elements.onlineReturnLink.addEventListener("click", handleOnlineReturnClick);
    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("online", handleOnline);
    window.addEventListener("storage", handleStorageChange);
    updateSelectionSummary();
    void refreshPendingCount();
  }

  function readCurrentOwner() {
    try {
      const value = window.localStorage.getItem(SESSION_OWNER_KEY);
      return value && UUID_PATTERN.test(value) ? value : null;
    } catch {
      return null;
    }
  }

  function readRequestedSelection() {
    const pathMatch = window.location.pathname.match(SCANNER_PATH_PATTERN);
    const groupId = pathMatch?.[1] && UUID_PATTERN.test(pathMatch[1])
      ? pathMatch[1]
      : null;
    const requestedSessionId = new URLSearchParams(window.location.search).get("sessionId");
    return {
      groupId,
      sessionId: requestedSessionId && UUID_PATTERN.test(requestedSessionId)
        ? requestedSessionId
        : null,
    };
  }

  async function readAuthorizedCoordinatorSelections(ownerId, requestedGroupId) {
    const database = await openQueueDatabase();
    try {
      const authorizationRows = await requestToPromise(
        database.transaction(AUTHORIZATION_STORE_NAME, "readonly")
          .objectStore(AUTHORIZATION_STORE_NAME)
          .getAll(),
      );
      const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
      const verified = [];
      for (const record of authorizationRows) {
        if (!isRecord(record) || record.ownerUserId !== ownerId) continue;
        try {
          const id = requiredString(record.id);
          if (!id || !isRecord(record.protectedValue)) continue;
          const storedValue = await decryptProtectedJson(
            storageKey,
            record.protectedValue,
            `coordinator-offline-authorization|${id}`,
          );
          const authorization = await verifyStoredAuthorization(database, record, storedValue);
          resolveAuthorizationTrustedTime(authorization);
          verified.push(authorization);
        } catch {
          // One corrupt or expired manifest must not make another independently
          // signed group unavailable.
        }
      }
      authorizationByGroup = new Map(
        verified.map((item) => [item.payload.group_id, item]),
      );
      const groups = verified.map((item) => ({
        id: item.payload.group_id,
        name: item.payload.group_label,
      }));
      const sessionsByGroup = new Map(
        verified.map((item) => [
          item.payload.group_id,
          item.payload.sessions.map((session) => ({
            id: session.id,
            groupId: item.payload.group_id,
            name: session.label,
            status: session.status,
          })),
        ]),
      );
      if (requestedGroupId && !authorizationByGroup.has(requestedGroupId)) {
        return { groups: [], sessionsByGroup: new Map() };
      }
      return { groups, sessionsByGroup };
    } finally {
      database.close();
    }
  }

  async function verifyStoredAuthorization(database, record, storedValue) {
    if (!isRecord(storedValue) || !isRecord(storedValue.bundle) || !isRecord(storedValue.payload)) {
      throw new Error("Signed authorization storage is invalid.");
    }
    const bundle = storedValue.bundle;
    const payloadBytes = decodeBase64url(requiredString(bundle.payload), 2 * 1024 * 1024);
    const signature = decodeBase64url(requiredString(bundle.signature), 64);
    const publicKey = decodeBase64url(requiredString(bundle.public_key), 32);
    const keyId = requiredString(bundle.key_id);
    const runtimeId = requiredString(record.runtimeId);
    if (
      !keyId
      || signature.length !== 64
      || publicKey.length !== 32
      || !isUuid(runtimeId)
      || !["pwa", "webview"].includes(record.runtimeKind)
      || parseRequiredInstant(record.runtimeExpiresAt) <= Date.now()
    ) {
      throw new Error("Signed authorization shape is invalid.");
    }
    const pinned = await readStoredCryptoKey(
      database,
      `offline-verification-key:${keyId}`,
    );
    const pinnedRecord = await requestToPromise(
      database.transaction(CRYPTO_KEY_STORE_NAME, "readonly")
        .objectStore(CRYPTO_KEY_STORE_NAME)
        .get(`offline-verification-key:${keyId}`),
    );
    if (!isRecord(pinnedRecord) || pinnedRecord.digest !== await sha256HexBytes(publicKey)) {
      throw new Error("Signed authorization key changed.");
    }
    const signatureValid = await window.crypto.subtle.verify(
      { name: "Ed25519" },
      pinned,
      signature,
      payloadBytes,
    );
    if (!signatureValid) throw new Error("Signed authorization signature is invalid.");
    const payload = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(payloadBytes));
    validateAuthorizationPayload(payload, record, keyId);
    return {
      bundle,
      payload,
      record,
      runtimeId,
      runtime: createAuthorizationRuntimeAnchor(record, payload),
    };
  }

  function validateAuthorizationPayload(payload, record, keyId) {
    if (
      !isRecord(payload)
      || payload.schema_version !== 1
      || payload.key_id !== keyId
      || payload.coordinator_user_id !== record.ownerUserId
      || payload.tenant_id !== record.agencyId
      || payload.group_id !== record.groupId
      || !isUuid(payload.group_id)
      || !requiredString(payload.group_label)
      || !Array.isArray(payload.sessions)
      || !Array.isArray(payload.passengers)
      || payload.sessions.length < 1
      || payload.sessions.length > 200
      || payload.passengers.length > 2000
    ) {
      throw new Error("Signed authorization binding is invalid.");
    }
    const serverTime = parseRequiredInstant(payload.server_time);
    const issuedAt = parseRequiredInstant(payload.issued_at);
    const notBefore = parseRequiredInstant(payload.not_before);
    const expiresAt = parseRequiredInstant(payload.expires_at);
    const maxSuspensionSeconds = Number(payload.max_suspension_seconds);
    if (
      issuedAt > serverTime
      || notBefore > serverTime + 2 * 60_000
      || expiresAt <= serverTime
      || !Number.isSafeInteger(maxSuspensionSeconds)
      || maxSuspensionSeconds < 60
      || maxSuspensionSeconds > 7 * 24 * 60 * 60
      || expiresAt - serverTime > maxSuspensionSeconds * 1000
    ) {
      throw new Error("Signed authorization time bounds are invalid.");
    }
    const sessionIds = new Set();
    for (const session of payload.sessions) {
      if (
        !isRecord(session)
        || !isUuid(session.id)
        || session.status !== "active"
        || !requiredString(session.label)
        || sessionIds.has(session.id)
        || parseRequiredInstant(session.scheduled_ends_at)
          <= parseRequiredInstant(session.scheduled_starts_at)
      ) {
        throw new Error("Signed attendance activity is invalid.");
      }
      sessionIds.add(session.id);
    }
    const passengerIds = new Set();
    const tokenHashes = new Set();
    for (const passenger of payload.passengers) {
      if (
        !isRecord(passenger)
        || !isUuid(passenger.id)
        || !requiredString(passenger.label)
        || typeof passenger.token_hash !== "string"
        || !/^[0-9a-f]{64}$/.test(passenger.token_hash)
        || passengerIds.has(passenger.id)
        || tokenHashes.has(passenger.token_hash)
      ) {
        throw new Error("Signed passenger evidence is invalid.");
      }
      parseRequiredInstant(passenger.token_valid_until);
      passengerIds.add(passenger.id);
      tokenHashes.add(passenger.token_hash);
    }
  }

  function createAuthorizationRuntimeAnchor(record, payload) {
    const wallNow = Date.now();
    const performanceNow = performance.now();
    const wallElapsed = wallNow - Number(record.observedWallClockMs);
    if (!Number.isFinite(wallElapsed) || wallElapsed < -2 * 60_000) {
      throw new Error("Trusted time rollback detected.");
    }
    if (wallElapsed > Number(payload.max_suspension_seconds) * 1000) {
      throw new Error("Offline suspension exceeded its signed bound.");
    }
    const trustedAtLaunch = Math.max(
      Number(record.trustedHighWaterMs),
      parseRequiredInstant(payload.server_time) + Math.max(0, wallElapsed),
    );
    return {
      observedPerformanceMs: performanceNow,
      observedWallClockMs: wallNow,
      trustedAtLaunchMs: trustedAtLaunch,
      trustedHighWaterMs: trustedAtLaunch,
    };
  }

  function resolveAuthorizationTrustedTime(authorization) {
    const { payload, runtime } = authorization;
    const monotonicElapsed = performance.now() - runtime.observedPerformanceMs;
    const wallElapsed = Date.now() - runtime.observedWallClockMs;
    if (
      !Number.isFinite(monotonicElapsed)
      || !Number.isFinite(wallElapsed)
      || monotonicElapsed < 0
      || wallElapsed < -2 * 60_000
      || Math.abs(wallElapsed - monotonicElapsed) > 2 * 60_000
    ) {
      throw new Error("Device clock changed after signed readiness was verified.");
    }
    const trusted = Math.max(
      runtime.trustedHighWaterMs,
      runtime.trustedAtLaunchMs + monotonicElapsed,
    );
    if (
      trusted - parseRequiredInstant(payload.server_time)
        > Number(payload.max_suspension_seconds) * 1000
    ) {
      throw new Error("Offline suspension exceeded its signed bound.");
    }
    if (trusted < parseRequiredInstant(payload.not_before) || trusted > parseRequiredInstant(payload.expires_at)) {
      throw new Error("Signed offline authorization expired.");
    }
    runtime.trustedHighWaterMs = Math.max(runtime.trustedHighWaterMs, Math.trunc(trusted));
    return runtime.trustedHighWaterMs;
  }

  async function authorizeDecodedScan(groupId, sessionId, qrPayload) {
    const authorization = authorizationByGroup.get(groupId);
    if (!authorization) throw new Error("No signed roster is available for this group.");
    const trustedNow = resolveAuthorizationTrustedTime(authorization);
    const session = authorization.payload.sessions.find((item) => item.id === sessionId);
    if (!session) throw new Error("This activity is not in the signed offline authorization.");
    if (
      trustedNow < parseRequiredInstant(session.scheduled_starts_at) - 5 * 60_000
      || trustedNow > parseRequiredInstant(session.scheduled_ends_at)
    ) {
      throw new Error("This activity is outside its signed attendance window.");
    }
    const tokenHash = await sha256HexBytes(new TextEncoder().encode(qrPayload));
    const matches = authorization.payload.passengers.filter((item) => item.token_hash === tokenHash);
    if (matches.length !== 1) throw new Error("This QR is not in the signed roster for this group.");
    const passenger = matches[0];
    if (trustedNow > parseRequiredInstant(passenger.token_valid_until)) {
      throw new Error("This passenger's signed QR evidence expired.");
    }
    await persistAuthorizationTrustedHighWater(authorization, trustedNow);
    return {
      passengerId: passenger.id,
      passengerLabel: passenger.label,
      scannedAt: new Date(trustedNow).toISOString(),
      sessionLabel: session.label,
    };
  }

  async function persistAuthorizationTrustedHighWater(authorization, trustedNow) {
    if (readCurrentOwner() !== authorization.record.ownerUserId) {
      throw new Error("The signed-in coordinator changed.");
    }
    const database = await openQueueDatabase();
    try {
      const transaction = database.transaction(AUTHORIZATION_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(AUTHORIZATION_STORE_NAME);
      const current = await requestToPromise(store.get(authorization.record.id));
      if (
        !isRecord(current)
        || current.ownerUserId !== authorization.record.ownerUserId
        || current.groupId !== authorization.record.groupId
      ) {
        transaction.abort();
        await completion.catch(() => undefined);
        throw new Error("Signed authorization ownership changed.");
      }
      const currentHighWater = Number(current.trustedHighWaterMs);
      if (!Number.isFinite(currentHighWater) || trustedNow > currentHighWater) {
        const updated = { ...current, trustedHighWaterMs: Math.trunc(trustedNow) };
        store.put(updated);
        authorization.record = updated;
      }
      await completion;
    } finally {
      database.close();
    }
  }

  function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function isUuid(value) {
    return typeof value === "string" && UUID_PATTERN.test(value);
  }

  function populateGroupOptions(preferredGroupId) {
    elements.groupSelect.replaceChildren();
    for (const group of cachedGroups) {
      const option = document.createElement("option");
      option.value = group.id;
      option.textContent = group.name;
      elements.groupSelect.append(option);
    }
    if (preferredGroupId && cachedGroups.some((group) => group.id === preferredGroupId)) {
      elements.groupSelect.value = preferredGroupId;
    }
  }

  function populateSessionOptions(preferredSessionId) {
    const sessions = sessionsByGroup.get(elements.groupSelect.value) ?? [];
    elements.sessionSelect.replaceChildren();
    for (const session of sessions) {
      const option = document.createElement("option");
      option.value = session.id;
      const statusSuffix = session.status ? ` - ${session.status}` : "";
      option.textContent = `${session.name}${statusSuffix}`;
      elements.sessionSelect.append(option);
    }
    if (
      preferredSessionId
      && sessions.some((session) => session.id === preferredSessionId)
    ) {
      elements.sessionSelect.value = preferredSessionId;
    }
    elements.sessionSelect.disabled = sessions.length === 0;
    elements.startButton.disabled = sessions.length === 0;
  }

  function handleGroupChange() {
    stopCamera("Group changed. Start the camera when ready.");
    populateSessionOptions(null);
    updateSelectionSummary();
    void refreshPendingCount();
  }

  function handleSessionChange() {
    stopCamera("Activity changed. Start the camera when ready.");
    updateSelectionSummary();
    void refreshPendingCount();
  }

  function updateSelectionSummary() {
    const session = getSelectedSession();
    elements.selectedActivity.textContent = session?.name ?? "No cached activity";
    elements.onlineReturnLink.href = getCoordinatorUrl();
  }

  function getSelectedSession() {
    const groupId = elements.groupSelect.value;
    const sessionId = elements.sessionSelect.value;
    return (sessionsByGroup.get(groupId) ?? []).find(
      (session) => session.id === sessionId,
    ) ?? null;
  }

  async function startCamera() {
    if (cameraStarting || scannerControls) return;
    if (!ownerUserId || !getSelectedSession()) {
      setFeedback("Select a cached group and activity first.", "error");
      return;
    }
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setFeedback(
        "Camera access is unavailable. Reopen this page from the secure coordinator app.",
        "error",
      );
      return;
    }
    if (!window.ZXingBrowser?.BrowserQRCodeReader) {
      setFeedback("The offline QR scanner did not load. Reconnect and reopen coordinator.", "error");
      return;
    }

    stopCamera("");
    const generation = cameraGeneration;
    cameraStarting = true;
    elements.startButton.disabled = true;
    elements.stopButton.disabled = false;
    elements.placeholder.hidden = true;
    setFeedback("Starting camera...", "info");

    try {
      codeReader = new window.ZXingBrowser.BrowserQRCodeReader(undefined, {
        delayBetweenScanSuccess: 700,
        delayBetweenScanAttempts: 100,
        tryPlayVideoTimeout: 5_000,
      });
      const controls = await codeReader.decodeFromConstraints(
        {
          audio: false,
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 960, max: 1280 },
            height: { ideal: 540, max: 720 },
            frameRate: { ideal: 24, max: 30 },
          },
        },
        elements.preview,
        handleDecode,
      );
      if (generation !== cameraGeneration || document.hidden) {
        controls.stop();
        releaseCameraStreams();
        return;
      }
      scannerControls = controls;
      setFeedback("Camera ready. Hold a passenger QR inside the frame.", "info");
    } catch (error) {
      if (generation !== cameraGeneration) return;
      stopCamera("");
      setFeedback(getCameraErrorMessage(error), "error");
    } finally {
      cameraStarting = false;
      elements.startButton.disabled = Boolean(scannerControls) || !getSelectedSession();
    }
  }

  function handleDecode(result) {
    if (!result) return;
    const qrPayload = typeof result.getText === "function"
      ? result.getText().trim()
      : "";
    if (!QR_PAYLOAD_PATTERN.test(qrPayload)) {
      setFeedback("This is not a valid Global Connects attendance QR.", "error");
      return;
    }

    const now = performance.now();
    if (qrPayload === lastDecodedPayload && now - lastDecodedAt < 2_500) {
      setFeedback("Already read this QR. It will be stored only once.", "duplicate");
      return;
    }
    lastDecodedPayload = qrPayload;
    lastDecodedAt = now;

    const selectedGroupId = elements.groupSelect.value;
    const selectedSession = getSelectedSession();
    if (!ownerUserId || !isUuid(selectedGroupId) || !selectedSession) {
      setFeedback("The selected cached activity is no longer available.", "error");
      return;
    }

    scanPipeline = scanPipeline
      .catch(() => undefined)
      .then(() => enqueueScan({
        ownerUserId,
        groupId: selectedGroupId,
        sessionId: selectedSession.id,
        qrPayload,
      }))
      .then((resultState) => {
        if (resultState.duplicate) {
          setFeedback("Already saved offline for this activity.", "duplicate");
        } else {
          setFeedback(
            "Saved offline as pending. It will count after server validation.",
            "success",
          );
        }
        return refreshPendingCount();
      })
      .catch((error) => {
        setFeedback(
          offlineAuthorizationErrorMessage(error),
          "error",
        );
      });
  }

  async function enqueueScan(selection) {
    if (readCurrentOwner() !== selection.ownerUserId) {
      throw new Error("The signed-in coordinator changed.");
    }
    const authorization = await authorizeDecodedScan(
      selection.groupId,
      selection.sessionId,
      selection.qrPayload,
    );
    const scanReference = await createScanReference(selection);
    const stableId = `attendance-scan:${scanReference}`;
    const timestamp = authorization.scannedAt;
    const recovery = {
      passengerId: authorization.passengerId,
      passengerLabel: authorization.passengerLabel,
      sessionLabel: authorization.sessionLabel,
    };
    const pendingMetadata = {
      groupId: selection.groupId,
      sessionId: selection.sessionId,
      clientEventId: createClientEventId(),
      scannedAt: timestamp,
      deviceId: authorization.runtimeId,
      runtimeId: authorization.runtimeId,
      id: stableId,
      scanReference,
      ownerUserId: selection.ownerUserId,
      queuedAt: timestamp,
      attemptCount: 0,
      nextAttemptAt: timestamp,
      deliveryState: "pending",
    };

    const db = await openQueueDatabase();
    try {
      if (readCurrentOwner() !== selection.ownerUserId) {
        throw new Error("The signed-in coordinator changed.");
      }
      const storageKey = await readStoredCryptoKey(db, STORAGE_KEY_ID);
      const protectedQrPayload = await encryptProtectedJson(
        storageKey,
        { qrPayload: selection.qrPayload, recovery },
        pendingScanAssociatedData(pendingMetadata),
      );
      const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(PENDING_STORE_NAME);
      try {
        const existing = await requestToPromise(store.get(stableId));
        if (!existing) {
          const ownerRowCount = await requestToPromise(
            store.index(OWNER_INDEX).count(selection.ownerUserId),
          );
          if (ownerRowCount >= MAX_PENDING_SCANS_PER_OWNER) {
            throw new Error("Offline attendance storage reached its safe device limit.");
          }
          await requestToPromise(store.put({
            ...pendingMetadata,
            protectedQrPayload,
            storageVersion: 5,
          }));
        }
        await completion;
        return { duplicate: Boolean(existing) };
      } catch (error) {
        await completion.catch(() => undefined);
        throw error;
      }
    } finally {
      db.close();
    }
  }

  async function refreshPendingCount() {
    const groupId = elements.groupSelect.value;
    const sessionId = elements.sessionSelect.value;
    if (!ownerUserId || !isUuid(groupId) || !isUuid(sessionId)) {
      elements.pendingCount.textContent = "0";
      return;
    }
    if (readCurrentOwner() !== ownerUserId) {
      handleOwnerChange();
      return;
    }

    try {
      const db = await openQueueDatabase();
      try {
        const transaction = db.transaction(PENDING_STORE_NAME, "readonly");
        const completion = transactionToPromise(transaction);
        const store = transaction.objectStore(PENDING_STORE_NAME);
        try {
          const scans = await requestToPromise(
            store.index(OWNER_INDEX).getAll(ownerUserId),
          );
          await completion;
          const count = scans.filter(
            (scan) =>
              isRecord(scan)
              && (!scan.groupId || scan.groupId === groupId)
              && scan.sessionId === sessionId,
          ).length;
          elements.pendingCount.textContent = String(count);
        } catch (error) {
          await completion.catch(() => undefined);
          throw error;
        }
      } finally {
        db.close();
      }
    } catch {
      elements.pendingCount.textContent = "Unavailable";
    }
  }

  function openQueueDatabase() {
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const database = request.result;
        const upgrade = request.transaction;
        if (!upgrade) return;
        // Never delete an unscoped legacy queue. Unattributable rows remain
        // quarantined until the online application can reconcile them.
        ensureOwnerScopedStore(database, upgrade, PENDING_STORE_NAME);
        ensureOwnerScopedStore(database, upgrade, REJECTED_STORE_NAME);
        ensureOwnerScopedStore(database, upgrade, DISCARD_STORE_NAME);
        ensureOwnerScopedStore(database, upgrade, SNAPSHOT_STORE_NAME);
        const authorizationStore = ensureOwnerScopedStore(
          database,
          upgrade,
          AUTHORIZATION_STORE_NAME,
        );
        if (!authorizationStore.indexNames.contains("expires-at")) {
          authorizationStore.createIndex("expires-at", "expiresAt", { unique: false });
        }
        const snapshotStore = upgrade.objectStore(SNAPSHOT_STORE_NAME);
        if (!snapshotStore.indexNames.contains("expires-at")) {
          snapshotStore.createIndex("expires-at", "expiresAt", { unique: false });
        }
        const discardStore = upgrade.objectStore(DISCARD_STORE_NAME);
        if (!discardStore.indexNames.contains("sync-state")) {
          discardStore.createIndex("sync-state", "syncState", { unique: false });
        }
        if (!database.objectStoreNames.contains(CRYPTO_KEY_STORE_NAME)) {
          database.createObjectStore(CRYPTO_KEY_STORE_NAME, { keyPath: "id" });
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        const migration = privacyMigrationPromise ??=
          migrateLegacyQueueRecords(database).catch((error) => {
            privacyMigrationPromise = null;
            throw error;
          });
        migration.then(() => resolve(database)).catch((error) => {
          database.close();
          reject(error);
        });
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () => reject(new Error("Offline scan database is busy."));
    });
  }

  function ensureOwnerScopedStore(database, upgrade, storeName) {
    const store = database.objectStoreNames.contains(storeName)
      ? upgrade.objectStore(storeName)
      : database.createObjectStore(storeName, { keyPath: "id" });
    if (!store.indexNames.contains(OWNER_INDEX)) {
      store.createIndex(OWNER_INDEX, "ownerUserId", { unique: false });
    }
    return store;
  }

  async function createScanReference(selection) {
    return hashReference([
      "attendance-scan-v4",
      selection.ownerUserId,
      selection.groupId || "legacy-group",
      selection.sessionId,
      selection.qrPayload,
    ]);
  }

  async function hashReference(parts) {
    if (!window.crypto?.subtle) {
      throw new Error("Secure SHA-256 support is required for offline attendance storage.");
    }
    const digest = await window.crypto.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(JSON.stringify(parts)),
    );
    const hex = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0")
    ).join("");
    return `sha256:${hex}`;
  }

  async function sha256HexBytes(bytes) {
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, "0")
    ).join("");
  }

  function pendingScanAssociatedData(scan) {
    return JSON.stringify([
      "attendance-pending-v5",
      scan.id,
      scan.ownerUserId,
      scan.groupId || "legacy-group",
      scan.sessionId,
    ]);
  }

  async function readStoredCryptoKey(database, id) {
    const record = await requestToPromise(
      database.transaction(CRYPTO_KEY_STORE_NAME, "readonly")
        .objectStore(CRYPTO_KEY_STORE_NAME)
        .get(id),
    );
    if (!isRecord(record) || !record.key || record.key.extractable !== false) {
      throw new Error("The protected offline key is unavailable.");
    }
    return record.key;
  }

  async function encryptProtectedJson(key, value, associatedData) {
    const plaintext = new TextEncoder().encode(JSON.stringify(value));
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    try {
      const ciphertext = await window.crypto.subtle.encrypt(
        {
          name: "AES-GCM",
          iv,
          additionalData: new TextEncoder().encode(associatedData),
          tagLength: 128,
        },
        key,
        plaintext,
      );
      return {
        algorithm: "AES-GCM",
        ciphertext,
        iv,
        keyId: STORAGE_KEY_ID,
        version: 1,
      };
    } finally {
      plaintext.fill(0);
    }
  }

  async function decryptProtectedJson(key, envelope, associatedData) {
    if (
      !isRecord(envelope)
      || envelope.version !== 1
      || envelope.algorithm !== "AES-GCM"
      || envelope.keyId !== STORAGE_KEY_ID
      || !(envelope.ciphertext instanceof ArrayBuffer)
      || !(envelope.iv instanceof Uint8Array)
      || envelope.iv.length !== 12
    ) {
      throw new Error("Protected offline data is invalid.");
    }
    const plaintext = new Uint8Array(await window.crypto.subtle.decrypt(
      {
        name: "AES-GCM",
        iv: envelope.iv,
        additionalData: new TextEncoder().encode(associatedData),
        tagLength: 128,
      },
      key,
      envelope.ciphertext,
    ));
    try {
      return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext));
    } finally {
      plaintext.fill(0);
    }
  }

  function decodeBase64url(value, maxBytes) {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value)) {
      throw new Error("Signed data is not canonical base64url.");
    }
    const padding = "=".repeat((4 - value.length % 4) % 4);
    const decoded = window.atob(value.replace(/-/g, "+").replace(/_/g, "/") + padding);
    if (decoded.length === 0 || decoded.length > maxBytes) {
      throw new Error("Signed data exceeds its bounded size.");
    }
    return Uint8Array.from(decoded, (character) => character.charCodeAt(0));
  }

  function parseRequiredInstant(value) {
    const parsed = typeof value === "string" ? Date.parse(value) : Number.NaN;
    if (!Number.isFinite(parsed)) throw new Error("Signed time is invalid.");
    return parsed;
  }

  function isScanReference(value) {
    return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
  }

  async function migrateLegacyQueueRecords(database) {
    const [pendingRows, rejectedRows] = await Promise.all([
      readAllQueueRows(database, PENDING_STORE_NAME),
      readAllQueueRows(database, REJECTED_STORE_NAME),
    ]);
    const [pendingReplacements, rejectedReplacements] = await Promise.all([
      Promise.all(pendingRows.map((row) => normalizePendingQueueRow(row, database).catch(() => null))),
      Promise.all(rejectedRows.map((row) => sanitizeRejectedQueueRow(row).catch(() => null))),
    ]);
    const transaction = database.transaction(
      [PENDING_STORE_NAME, REJECTED_STORE_NAME],
      "readwrite",
    );
    const completion = transactionToPromise(transaction);
    replaceQueueRows(
      transaction.objectStore(PENDING_STORE_NAME),
      pendingRows,
      pendingReplacements,
    );
    replaceQueueRows(
      transaction.objectStore(REJECTED_STORE_NAME),
      rejectedRows,
      rejectedReplacements,
    );
    await completion;
  }

  async function normalizePendingQueueRow(candidate, database) {
    if (!isRecord(candidate)) return null;
    if (candidate.storageVersion === 5 && isRecord(candidate.protectedQrPayload)) {
      const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
      const decrypted = await decryptProtectedJson(
        storageKey,
        candidate.protectedQrPayload,
        pendingScanAssociatedData(candidate),
      );
      if (!isRecord(decrypted) || !QR_PAYLOAD_PATTERN.test(decrypted.qrPayload)) {
        throw new Error("Protected attendance queue row is corrupt.");
      }
      const expected = await createScanReference({
        ownerUserId: candidate.ownerUserId,
        groupId: candidate.groupId,
        sessionId: candidate.sessionId,
        qrPayload: decrypted.qrPayload,
      });
      if (expected !== candidate.scanReference) throw new Error("Protected queue identity failed.");
      return candidate;
    }
    const ownerId = requiredString(candidate.ownerUserId);
    const sessionId = requiredString(candidate.sessionId);
    const qrPayload = requiredString(candidate.qrPayload);
    const clientEventId = requiredString(candidate.clientEventId);
    const scannedAt = requiredString(candidate.scannedAt);
    const deviceId = requiredString(candidate.deviceId);
    const queuedAt = requiredString(candidate.queuedAt);
    if (!ownerId || !sessionId || !qrPayload || !clientEventId || !scannedAt || !deviceId || !queuedAt) {
      return null;
    }
    const groupId = requiredString(candidate.groupId);
    const scanReference = isScanReference(candidate.scanReference)
      ? candidate.scanReference
      : await createScanReference({
          ownerUserId: ownerId,
          groupId,
          sessionId,
          qrPayload,
        });
    const nextAttemptAt = validIso(candidate.nextAttemptAt) || queuedAt;
    const lastAttemptAt = validIso(candidate.lastAttemptAt);
    const metadata = {
      id: `attendance-scan:${scanReference}`,
      scanReference,
      ownerUserId: ownerId,
      ...(groupId ? { groupId } : {}),
      sessionId,
      clientEventId,
      scannedAt,
      deviceId,
      queuedAt,
      attemptCount: Number.isFinite(candidate.attemptCount)
        ? Math.max(0, Math.trunc(candidate.attemptCount))
        : 0,
      nextAttemptAt,
      deliveryState: candidate.deliveryState === "sending" ? "sending" : "pending",
      ...(lastAttemptAt ? { lastAttemptAt } : {}),
    };
    const storageKey = await readStoredCryptoKey(database, STORAGE_KEY_ID);
    const protectedQrPayload = await encryptProtectedJson(
      storageKey,
      { qrPayload },
      pendingScanAssociatedData(metadata),
    );
    const verified = await decryptProtectedJson(
      storageKey,
      protectedQrPayload,
      pendingScanAssociatedData(metadata),
    );
    if (!isRecord(verified) || verified.qrPayload !== qrPayload) {
      throw new Error("Legacy queue encryption verification failed.");
    }
    return { ...metadata, protectedQrPayload, storageVersion: 5 };
  }

  async function sanitizeRejectedQueueRow(candidate) {
    if (!isRecord(candidate)) return null;
    const ownerId = requiredString(candidate.ownerUserId);
    const sessionId = requiredString(candidate.sessionId);
    const clientEventId = requiredString(candidate.clientEventId);
    const scannedAt = requiredString(candidate.scannedAt);
    const deviceId = requiredString(candidate.deviceId);
    const queuedAt = requiredString(candidate.queuedAt);
    const rejectedAt = requiredString(candidate.rejectedAt);
    const errorCode = requiredString(candidate.errorCode);
    if (!ownerId || !sessionId || !clientEventId || !scannedAt || !deviceId || !queuedAt || !rejectedAt || !errorCode) {
      return null;
    }
    const groupId = requiredString(candidate.groupId);
    const qrPayload = requiredString(candidate.qrPayload);
    const scanReference = isScanReference(candidate.scanReference)
      ? candidate.scanReference
      : qrPayload
        ? await createScanReference({
            ownerUserId: ownerId,
            groupId,
            sessionId,
            qrPayload,
          })
        : await hashReference([
            "attendance-terminal-v4",
            ownerId,
            groupId || "legacy-group",
            sessionId,
            clientEventId,
            requiredString(candidate.id) || "missing-id",
          ]);
    return {
      id: `attendance-rejected:${scanReference}`,
      scanReference,
      ownerUserId: ownerId,
      ...(groupId ? { groupId } : {}),
      sessionId,
      clientEventId,
      scannedAt,
      deviceId,
      queuedAt,
      rejectedAt,
      errorCode,
    };
  }

  function readAllQueueRows(database, storeName) {
    const store = database.transaction(storeName, "readonly").objectStore(storeName);
    return requestToPromise(store.getAll());
  }

  function replaceQueueRows(store, originals, replacements) {
    originals.forEach((original, index) => {
      const oldId = isRecord(original) ? requiredString(original.id) : null;
      const replacement = replacements[index];
      if (replacement) {
        store.put(replacement);
        if (oldId && oldId !== replacement.id) store.delete(oldId);
      }
    });
  }

  function requiredString(value) {
    return typeof value === "string" && value.length > 0 ? value : null;
  }

  function validIso(value) {
    return typeof value === "string" && Number.isFinite(Date.parse(value))
      ? value
      : null;
  }

  function requestToPromise(request) {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function transactionToPromise(transaction) {
    return new Promise((resolve, reject) => {
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(
        transaction.error ?? new Error("Offline scan transaction was aborted."),
      );
    });
  }

  function createClientEventId() {
    return secureRandomUuid();
  }

  function secureRandomUuid() {
    if (typeof window.crypto?.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }

  function stopCamera(message) {
    cameraGeneration += 1;
    try {
      scannerControls?.stop();
    } catch {
      // Camera teardown is best-effort across mobile browser implementations.
    }
    scannerControls = null;
    releaseCameraStreams();
    codeReader = null;
    elements.startButton.disabled = cameraStarting || !getSelectedSession();
    elements.stopButton.disabled = true;
    elements.placeholder.hidden = false;
    if (message) setFeedback(message, "info");
  }

  function releaseCameraStreams() {
    try {
      window.ZXingBrowser?.BrowserCodeReader?.releaseAllStreams();
    } catch {
      // Also stop the element stream below for browsers with partial controls.
    }
    const stream = elements.preview.srcObject;
    if (stream && typeof stream.getTracks === "function") {
      for (const track of stream.getTracks()) track.stop();
    }
    elements.preview.srcObject = null;
  }

  function handleVisibilityChange() {
    if (document.hidden) stopCamera("Camera paused while the app is hidden.");
  }

  function handlePageHide() {
    stopCamera("");
  }

  function handleOnline() {
    if (reconnectInProgress) return;
    reconnectInProgress = true;
    stopCamera("");
    const coordinatorUrl = getCoordinatorUrl();
    elements.onlineReturnLink.href = coordinatorUrl;
    elements.onlineBanner.hidden = false;
    // A QR decode may already be inside its IndexedDB commit. Never tear down
    // this document until the serialized scan pipeline has settled.
    void scanPipeline
      .catch(() => undefined)
      .finally(() => {
        if (!ownerUserId || readCurrentOwner() !== ownerUserId) {
          reconnectInProgress = false;
          handleOwnerChange();
          return;
        }
        window.location.replace(coordinatorUrl);
      });
  }

  function handleOnlineReturnClick(event) {
    if (reconnectInProgress) event.preventDefault();
  }

  function handleStorageChange(event) {
    if (event.key === SESSION_OWNER_KEY && event.newValue !== ownerUserId) {
      handleOwnerChange();
    }
  }

  function handleOwnerChange() {
    stopCamera("");
    ownerUserId = null;
    showUnavailable(
      "Coordinator session changed",
      "Reconnect and sign in again before recording more attendance scans.",
    );
  }

  function getCoordinatorUrl() {
    const groupId = elements.groupSelect?.value;
    const sessionId = elements.sessionSelect?.value;
    if (isUuid(groupId) && isUuid(sessionId)) {
      return `/coordinator/groups/${encodeURIComponent(groupId)}/scanner?sessionId=${encodeURIComponent(sessionId)}`;
    }
    return "/coordinator";
  }

  function getCameraErrorMessage(error) {
    const name = isRecord(error) && typeof error.name === "string" ? error.name : "";
    if (name === "NotAllowedError" || name === "SecurityError") {
      return "Camera permission was denied. Allow camera access and try again.";
    }
    if (name === "NotFoundError" || name === "DevicesNotFoundError") {
      return "No camera was found on this device.";
    }
    if (name === "NotReadableError" || name === "TrackStartError") {
      return "The camera is already in use by another app.";
    }
    return "The camera could not start. Close other camera apps and try again.";
  }

  function offlineAuthorizationErrorMessage(error) {
    const message = error instanceof Error ? error.message : "";
    if (/safe device limit/i.test(message)) {
      return "Offline scan storage is full. Reconnect and synchronize saved scans before continuing.";
    }
    if (/not in the signed roster/i.test(message)) {
      return "Wrong group or unauthorized passenger. This QR was not saved.";
    }
    if (/activity|window/i.test(message)) {
      return "This signed activity is unavailable, not yet valid, or closed. This QR was not saved.";
    }
    if (/time|expired|suspension|rollback/i.test(message)) {
      return "Trusted offline time is unavailable or expired. Reconnect before scanning.";
    }
    return "Could not protect this scan on the device. Keep the QR available and reconnect.";
  }

  function setFeedback(message, tone) {
    elements.feedback.textContent = message;
    elements.feedback.dataset.tone = tone;
  }

  function showUnavailable(title, message) {
    elements.generic.hidden = true;
    elements.scanner.hidden = true;
    elements.unavailableTitle.textContent = title;
    elements.unavailableMessage.textContent = message;
    elements.unavailable.hidden = false;
  }
})();
