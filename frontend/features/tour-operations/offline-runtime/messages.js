import { isRecord } from './values.js';

export function getCameraErrorMessage(error) {
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

export function offlineAuthorizationErrorMessage(error) {
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
