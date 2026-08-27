export function photoPreviewAccessibilityLabel(
  sourceAvailable: boolean,
  positionLabel: string,
  unavailableLabel: string,
): string {
  return sourceAvailable ? positionLabel : unavailableLabel;
}
