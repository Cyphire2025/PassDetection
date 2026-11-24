import { createOfflineAuthorization } from './authorization.js';
import { createOfflineCamera } from './camera.js';
import {
  COORDINATOR_PATH_PATTERN,
  OWNER_INDEX,
  PENDING_STORE_NAME,
  QR_PAYLOAD_PATTERN,
  SESSION_OWNER_KEY,
} from './constants.js';
import { openQueueDatabase } from './database.js';
import { requestToPromise, transactionToPromise } from './idb-requests.js';
import { offlineAuthorizationErrorMessage } from './messages.js';
import { createPendingScanQueue } from './pending-scans.js';
import { isRecord, isUuid, readCurrentOwner, readRequestedSelection } from './values.js';
import { createScannerView } from './view.js';

export function initializeOfflineScanner() {
  const state = { ownerUserId: null, cachedGroups: [], sessionsByGroup: new Map() };
  const view = createScannerView(state);
  const authorization = createOfflineAuthorization();
  const { readAuthorizedCoordinatorSelections } = authorization;
  const { enqueueScan } = createPendingScanQueue(authorization);
  const { startCamera, stopCamera } = createOfflineCamera(state, view, handleDecode);
  const { elements, populateGroupOptions, populateSessionOptions, getSelectedSession,
    updateSelectionSummary, getCoordinatorUrl, setFeedback, showUnavailable } = view;

  let scanPipeline = Promise.resolve();

  let lastDecodedPayload = "";

  let lastDecodedAt = 0;

  let reconnectInProgress = false;

  async function initialize() {
    if (!COORDINATOR_PATH_PATTERN.test(window.location.pathname)) return;
  
    state.ownerUserId = readCurrentOwner();
    if (!state.ownerUserId) {
      showUnavailable(
        "Offline scanner unavailable",
        "No valid signed-in coordinator snapshot is available. Reconnect and sign in again.",
      );
      return;
    }
  
    const requested = readRequestedSelection();
    let snapshot;
    try {
      snapshot = await readAuthorizedCoordinatorSelections(state.ownerUserId, requested.groupId);
    } catch {
      showUnavailable(
        "Signed offline readiness unavailable",
        "Reconnect and open this activity online to verify its signed roster and schedule.",
      );
      return;
    }
    if (readCurrentOwner() !== state.ownerUserId) {
      handleOwnerChange();
      return;
    }
    state.cachedGroups = snapshot.groups;
    state.sessionsByGroup = snapshot.sessionsByGroup;
  
    if (state.cachedGroups.length === 0) {
      showUnavailable(
        "No cached groups",
        "Reconnect and open an assigned coordinator group once before scanning offline.",
      );
      return;
    }
  
    const groupsWithSessions = state.cachedGroups.filter(
      (group) => (state.sessionsByGroup.get(group.id) ?? []).length > 0,
    );
    if (groupsWithSessions.length === 0) {
      showUnavailable(
        "No cached activities",
        "Reconnect and open an attendance activity once before scanning offline.",
      );
      return;
    }
  
    state.cachedGroups = groupsWithSessions;
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
    if (!state.ownerUserId || !isUuid(selectedGroupId) || !selectedSession) {
      setFeedback("The selected cached activity is no longer available.", "error");
      return;
    }
  
    scanPipeline = scanPipeline
      .catch(() => undefined)
      .then(() => enqueueScan({
        ownerUserId: state.ownerUserId,
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

  async function refreshPendingCount() {
    const ownerId = state.ownerUserId;
    const groupId = elements.groupSelect.value;
    const sessionId = elements.sessionSelect.value;
    if (!state.ownerUserId || !isUuid(groupId) || !isUuid(sessionId)) {
      elements.pendingCount.textContent = "0";
      return;
    }
    if (readCurrentOwner() !== state.ownerUserId) {
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
            store.index(OWNER_INDEX).getAll(ownerId),
          );
          await completion;
          const count = scans.filter(
            (scan) =>
              isRecord(scan)
              && (!scan.groupId || scan.groupId === groupId)
              && scan.sessionId === sessionId,
          ).length;
          if (canPublishPendingCount(ownerId, groupId, sessionId)) {
            elements.pendingCount.textContent = String(count);
          }
        } catch (error) {
          await completion.catch(() => undefined);
          throw error;
        }
      } finally {
        db.close();
      }
    } catch {
      if (canPublishPendingCount(ownerId, groupId, sessionId)) {
        elements.pendingCount.textContent = "Unavailable";
      }
    }
  }

  function canPublishPendingCount(ownerId, groupId, sessionId) {
    if (state.ownerUserId !== ownerId) return false;
    if (readCurrentOwner() !== ownerId) {
      handleOwnerChange();
      return false;
    }
    return elements.groupSelect.value === groupId && elements.sessionSelect.value === sessionId;
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
        if (!state.ownerUserId || readCurrentOwner() !== state.ownerUserId) {
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
    if (event.key === SESSION_OWNER_KEY && event.newValue !== state.ownerUserId) {
      handleOwnerChange();
    }
  }

  function handleOwnerChange() {
    stopCamera("");
    state.ownerUserId = null;
    state.cachedGroups = [];
    state.sessionsByGroup.clear();
    authorization.clearAuthorizations();
    view.clearPrivateSelection();
    lastDecodedPayload = "";
    lastDecodedAt = 0;
    showUnavailable(
      "Coordinator session changed",
      "Reconnect and sign in again before recording more attendance scans.",
    );
  }

  void initialize();
}
