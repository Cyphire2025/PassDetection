import { isUuid } from './values.js';

export function createScannerView(state) {
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

  function populateGroupOptions(preferredGroupId) {
    elements.groupSelect.replaceChildren();
    for (const group of state.cachedGroups) {
      const option = document.createElement("option");
      option.value = group.id;
      option.textContent = group.name;
      elements.groupSelect.append(option);
    }
    if (preferredGroupId && state.cachedGroups.some((group) => group.id === preferredGroupId)) {
      elements.groupSelect.value = preferredGroupId;
    }
  }

  function populateSessionOptions(preferredSessionId) {
    const sessions = state.sessionsByGroup.get(elements.groupSelect.value) ?? [];
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

  function updateSelectionSummary() {
    const session = getSelectedSession();
    elements.selectedActivity.textContent = session?.name ?? "No cached activity";
    elements.onlineReturnLink.href = getCoordinatorUrl();
  }

  function getSelectedSession() {
    const groupId = elements.groupSelect.value;
    const sessionId = elements.sessionSelect.value;
    return (state.sessionsByGroup.get(groupId) ?? []).find(
      (session) => session.id === sessionId,
    ) ?? null;
  }

  function getCoordinatorUrl() {
    const groupId = elements.groupSelect?.value;
    const sessionId = elements.sessionSelect?.value;
    if (isUuid(groupId) && isUuid(sessionId)) {
      return `/coordinator/groups/${encodeURIComponent(groupId)}/scanner?sessionId=${encodeURIComponent(sessionId)}`;
    }
    return "/coordinator";
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

  function clearPrivateSelection() {
    elements.groupSelect.replaceChildren();
    elements.sessionSelect.replaceChildren();
    elements.selectedActivity.textContent = "No cached activity";
    elements.pendingCount.textContent = "0";
    elements.feedback.textContent = "";
    elements.onlineReturnLink.href = "/coordinator";
    elements.onlineBanner.hidden = true;
  }

  return {
    elements,
    populateGroupOptions,
    populateSessionOptions,
    updateSelectionSummary,
    getSelectedSession,
    getCoordinatorUrl,
    setFeedback,
    showUnavailable,
    clearPrivateSelection,
  };
}
