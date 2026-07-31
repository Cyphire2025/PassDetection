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
  const GROUPS_SNAPSHOT_KEY = "passdetection-tour-ops-my-groups";
  const SESSIONS_SNAPSHOT_KEY = "passdetection-tour-ops-my-sessions";
  const DEVICE_ID_KEY = "passdetection-coordinator-device-id";
  const DB_NAME = "passdetection-tour-ops";
  const DB_VERSION = 4;
  const PENDING_STORE_NAME = "pending-attendance-scans";
  const REJECTED_STORE_NAME = "rejected-attendance-scans";
  const OWNER_INDEX = "owner-user-id";
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

  initialize();

  function initialize() {
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
    const snapshot = readCoordinatorSnapshots(ownerUserId, requested.groupId);
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

  function readCoordinatorSnapshots(ownerId, requestedGroupId) {
    const rawGroups = readJsonArray(`${GROUPS_SNAPSHOT_KEY}:user:${ownerId}`);
    const groups = [];
    const seenGroupIds = new Set();

    for (const candidate of rawGroups) {
      const group = validateGroup(candidate);
      if (!group || seenGroupIds.has(group.id)) continue;
      seenGroupIds.add(group.id);
      groups.push(group);
    }

    const groupIdsToRead = groups.map((group) => group.id);
    if (
      requestedGroupId
      && UUID_PATTERN.test(requestedGroupId)
      && !seenGroupIds.has(requestedGroupId)
    ) {
      groupIdsToRead.push(requestedGroupId);
    }

    const sessionMap = new Map();
    for (const groupId of groupIdsToRead) {
      const rawSessions = readJsonArray(
        `${SESSIONS_SNAPSHOT_KEY}:${groupId}:user:${ownerId}`,
      );
      const sessions = [];
      const seenSessionIds = new Set();
      for (const candidate of rawSessions) {
        const session = validateSession(candidate, groupId);
        if (!session || seenSessionIds.has(session.id)) continue;
        seenSessionIds.add(session.id);
        sessions.push(session);
      }
      sessionMap.set(groupId, sessions);

      if (
        sessions.length > 0
        && requestedGroupId === groupId
        && !seenGroupIds.has(groupId)
      ) {
        seenGroupIds.add(groupId);
        groups.unshift({ id: groupId, name: "Cached coordinator group" });
      }
    }

    return { groups, sessionsByGroup: sessionMap };
  }

  function readJsonArray(key) {
    try {
      const value = window.localStorage.getItem(key);
      if (!value) return [];
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }

  function validateGroup(candidate) {
    if (!isRecord(candidate) || !isUuid(candidate.id)) return null;
    return {
      id: candidate.id,
      name: safeLabel(candidate.name, "Cached coordinator group"),
    };
  }

  function validateSession(candidate, expectedGroupId) {
    if (
      !isRecord(candidate)
      || !isUuid(candidate.id)
      || candidate.group_id !== expectedGroupId
    ) {
      return null;
    }
    return {
      id: candidate.id,
      groupId: expectedGroupId,
      name: safeLabel(candidate.name, "Cached attendance activity"),
      status: safeLabel(candidate.status, ""),
    };
  }

  function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function isUuid(value) {
    return typeof value === "string" && UUID_PATTERN.test(value);
  }

  function safeLabel(value, fallback) {
    if (typeof value !== "string") return fallback;
    const normalized = value.trim().replace(/\s+/g, " ");
    return normalized ? normalized.slice(0, 120) : fallback;
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

    const now = Date.now();
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
      .catch(() => {
        setFeedback(
          "Could not save this scan on the device. Keep the QR and try again.",
          "error",
        );
      });
  }

  async function enqueueScan(selection) {
    if (readCurrentOwner() !== selection.ownerUserId) {
      throw new Error("The signed-in coordinator changed.");
    }
    const stableId =
      `${selection.ownerUserId}:${selection.groupId}:${selection.sessionId}:${selection.qrPayload}`;
    const legacyId =
      `${selection.ownerUserId}:${selection.sessionId}:${selection.qrPayload}`;
    const timestamp = new Date().toISOString();
    const pendingScan = {
      groupId: selection.groupId,
      sessionId: selection.sessionId,
      qrPayload: selection.qrPayload,
      clientEventId: createClientEventId(),
      scannedAt: timestamp,
      deviceId: getDeviceId(),
      id: stableId,
      ownerUserId: selection.ownerUserId,
      queuedAt: timestamp,
    };

    const db = await openQueueDatabase();
    try {
      if (readCurrentOwner() !== selection.ownerUserId) {
        throw new Error("The signed-in coordinator changed.");
      }
      const transaction = db.transaction(PENDING_STORE_NAME, "readwrite");
      const completion = transactionToPromise(transaction);
      const store = transaction.objectStore(PENDING_STORE_NAME);
      try {
        const existing = (
          await requestToPromise(store.get(stableId))
        ) ?? (
          await requestToPromise(store.get(legacyId))
        );
        if (!existing) await requestToPromise(store.put(pendingScan));
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
      request.onupgradeneeded = (event) => {
        const database = request.result;
        const upgrade = request.transaction;
        if (!upgrade) return;

        // Match the app's queue upgrade contract. Version 1 was unscoped and
        // cannot be attributed safely; all owner-scoped v2/v3 records survive.
        if (
          database.objectStoreNames.contains(PENDING_STORE_NAME)
          && event.oldVersion < 2
        ) {
          database.deleteObjectStore(PENDING_STORE_NAME);
        }
        ensureOwnerScopedStore(database, upgrade, PENDING_STORE_NAME);
        const rejectedStore = ensureOwnerScopedStore(
          database,
          upgrade,
          REJECTED_STORE_NAME,
        );
        if (event.oldVersion < 4) {
          migrateRejectedAttendanceScans(rejectedStore);
        }
      };
      request.onsuccess = () => {
        const database = request.result;
        database.onversionchange = () => database.close();
        resolve(database);
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

  function migrateRejectedAttendanceScans(store) {
    const request = store.openCursor();
    request.onsuccess = () => {
      const cursor = request.result;
      if (!cursor) return;

      const migrated = projectRejectedAttendanceScanForStorage(
        cursor.value,
        createClientEventId(),
      );
      if (!migrated) {
        cursor.delete();
        cursor.continue();
        return;
      }

      store.put(migrated);
      if (cursor.primaryKey !== migrated.id) {
        store.delete(cursor.primaryKey);
      }
      cursor.continue();
    };
  }

  function projectRejectedAttendanceScanForStorage(value, fallbackClientEventId) {
    if (!value || typeof value !== "object") return null;
    const ownerUserId = requiredStoredString(value.ownerUserId);
    const sessionId = requiredStoredString(value.sessionId);
    const clientEventId = requiredStoredString(value.clientEventId)
      || requiredStoredString(fallbackClientEventId);
    if (!ownerUserId || !sessionId || !clientEventId) return null;

    const groupId = requiredStoredString(value.groupId) || undefined;
    const rejectedAt = requiredStoredString(value.rejectedAt)
      || new Date().toISOString();
    const queuedAt = requiredStoredString(value.queuedAt) || rejectedAt;
    return {
      groupId,
      sessionId,
      clientEventId,
      scannedAt: requiredStoredString(value.scannedAt) || queuedAt,
      deviceId: requiredStoredString(value.deviceId) || "unknown",
      ownerUserId,
      queuedAt,
      id: `${ownerUserId}:${groupId || "legacy"}:${sessionId}:${clientEventId}`,
      rejectedAt,
      errorCode: requiredStoredString(value.errorCode) || "UNKNOWN",
    };
  }

  function requiredStoredString(value) {
    return typeof value === "string" && value.length > 0 ? value : null;
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
    const randomPart = typeof window.crypto?.randomUUID === "function"
      ? window.crypto.randomUUID()
      : Math.random().toString(36).slice(2);
    return `${Date.now()}-${randomPart}`;
  }

  function getDeviceId() {
    try {
      const existing = window.localStorage.getItem(DEVICE_ID_KEY);
      if (existing) return existing;
      const next = typeof window.crypto?.randomUUID === "function"
        ? window.crypto.randomUUID()
        : `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      window.localStorage.setItem(DEVICE_ID_KEY, next);
      return next;
    } catch {
      return `device-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
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
