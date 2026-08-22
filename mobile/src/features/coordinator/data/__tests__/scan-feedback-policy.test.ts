import {
  attendanceScanSoundKind,
  createScanFeedbackWav,
  SCAN_FEEDBACK_TONES,
} from '../scan-feedback-policy';

test('assigns distinct outcome sounds while treating a durable save as success', () => {
  expect(attendanceScanSoundKind('saved')).toBe('success');
  expect(attendanceScanSoundKind('success')).toBe('success');
  expect(attendanceScanSoundKind('duplicate')).toBe('duplicate');
  expect(attendanceScanSoundKind('failure')).toBe('failure');
});

test('builds valid, bounded, distinct offline PCM wave files', () => {
  const success = createScanFeedbackWav(SCAN_FEEDBACK_TONES.success);
  const duplicate = createScanFeedbackWav(SCAN_FEEDBACK_TONES.duplicate);
  const failure = createScanFeedbackWav(SCAN_FEEDBACK_TONES.failure);

  for (const wav of [success, duplicate, failure]) {
    expect(String.fromCharCode(...wav.slice(0, 4))).toBe('RIFF');
    expect(String.fromCharCode(...wav.slice(8, 12))).toBe('WAVE');
    expect(wav.byteLength).toBeLessThan(10_000);
  }
  expect([...success]).not.toEqual([...duplicate]);
  expect([...duplicate]).not.toEqual([...failure]);
});
