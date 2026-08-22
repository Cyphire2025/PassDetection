export type AttendanceScanFeedbackKind =
  | 'saved'
  | 'success'
  | 'duplicate'
  | 'failure';

export type AttendanceScanSoundKind = 'success' | 'duplicate' | 'failure';

export type ScanFeedbackToneSegment = Readonly<{
  frequencyHz: number;
  durationMs: number;
  amplitude: number;
}>;

const SAMPLE_RATE = 8_000;

export const SCAN_FEEDBACK_TONES = Object.freeze({
  success: Object.freeze([
    { frequencyHz: 880, durationMs: 85, amplitude: 0.34 },
    { frequencyHz: 0, durationMs: 25, amplitude: 0 },
    { frequencyHz: 1_320, durationMs: 120, amplitude: 0.34 },
  ]),
  duplicate: Object.freeze([
    { frequencyHz: 560, durationMs: 75, amplitude: 0.28 },
    { frequencyHz: 0, durationMs: 65, amplitude: 0 },
    { frequencyHz: 560, durationMs: 75, amplitude: 0.28 },
  ]),
  failure: Object.freeze([
    { frequencyHz: 360, durationMs: 135, amplitude: 0.32 },
    { frequencyHz: 230, durationMs: 190, amplitude: 0.34 },
  ]),
} satisfies Readonly<Record<AttendanceScanSoundKind, readonly ScanFeedbackToneSegment[]>>);

export function attendanceScanSoundKind(
  feedback: AttendanceScanFeedbackKind,
): AttendanceScanSoundKind {
  if (feedback === 'duplicate') return 'duplicate';
  if (feedback === 'failure') return 'failure';
  return 'success';
}

function writeAscii(view: DataView, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

/** Builds a bounded 16-bit mono PCM WAV so feedback remains bundled/offline. */
export function createScanFeedbackWav(
  segments: readonly ScanFeedbackToneSegment[],
): Uint8Array {
  const sampleCounts = segments.map((segment) => (
    Math.max(1, Math.round((segment.durationMs / 1_000) * SAMPLE_RATE))
  ));
  const totalSamples = sampleCounts.reduce((total, count) => total + count, 0);
  const dataBytes = totalSamples * 2;
  const bytes = new Uint8Array(44 + dataBytes);
  const view = new DataView(bytes.buffer);
  writeAscii(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);
  writeAscii(view, 8, 'WAVEfmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, 'data');
  view.setUint32(40, dataBytes, true);

  let outputIndex = 0;
  segments.forEach((segment, segmentIndex) => {
    const segmentSamples = sampleCounts[segmentIndex] ?? 1;
    const fadeSamples = Math.min(Math.round(SAMPLE_RATE * 0.008), Math.floor(segmentSamples / 2));
    for (let index = 0; index < segmentSamples; index += 1) {
      const fadeIn = fadeSamples === 0 ? 1 : Math.min(1, index / fadeSamples);
      const fadeOut = fadeSamples === 0
        ? 1
        : Math.min(1, (segmentSamples - index - 1) / fadeSamples);
      const envelope = Math.max(0, Math.min(fadeIn, fadeOut));
      const value = segment.frequencyHz <= 0
        ? 0
        : Math.sin((2 * Math.PI * segment.frequencyHz * index) / SAMPLE_RATE)
          * segment.amplitude
          * envelope;
      view.setInt16(44 + outputIndex * 2, Math.round(value * 32_767), true);
      outputIndex += 1;
    }
  });
  return bytes;
}
