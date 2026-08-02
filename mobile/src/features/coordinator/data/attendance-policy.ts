export function attendanceDedupeMaterial(
  account: string,
  tripId: string,
  sessionId: string,
  signedQr: string,
): string {
  return `${account}|${tripId}|${sessionId}|${signedQr}`;
}
