import { useAudioPlayer, setAudioModeAsync, type AudioPlayer } from 'expo-audio';
import { File, Paths } from 'expo-file-system';
import * as Haptics from 'expo-haptics';
import * as SecureStore from 'expo-secure-store';
import { useCallback, useEffect, useRef, useState } from 'react';

import { secureValuePolicy } from '@/core/storage/secure-store-policy';
import {
  attendanceScanSoundKind,
  createScanFeedbackWav,
  SCAN_FEEDBACK_TONES,
  type AttendanceScanFeedbackKind,
  type AttendanceScanSoundKind,
} from '@/features/coordinator/data/scan-feedback-policy';

const PREFERENCE_KEY = 'global.scan-feedback-audio.v1';
const PREFERENCE_OPTIONS = secureValuePolicy('scan-feedback-preference').options;

const SOUND_FILES: Readonly<Record<AttendanceScanSoundKind, string>> = Object.freeze({
  success: 'gc-scan-success-v1.wav',
  duplicate: 'gc-scan-duplicate-v1.wav',
  failure: 'gc-scan-failure-v1.wav',
});

function ensureSoundFiles(): Readonly<Record<AttendanceScanSoundKind, string>> {
  const sources = {} as Record<AttendanceScanSoundKind, string>;
  (Object.keys(SOUND_FILES) as AttendanceScanSoundKind[]).forEach((kind) => {
    const file = new File(Paths.cache, SOUND_FILES[kind]);
    if (!file.exists) file.create({ intermediates: true });
    file.write(createScanFeedbackWav(SCAN_FEEDBACK_TONES[kind]));
    sources[kind] = file.uri;
  });
  return sources;
}

function hapticType(kind: AttendanceScanFeedbackKind): Haptics.NotificationFeedbackType {
  if (kind === 'failure') return Haptics.NotificationFeedbackType.Error;
  if (kind === 'success') return Haptics.NotificationFeedbackType.Success;
  return Haptics.NotificationFeedbackType.Warning;
}

function replay(player: AudioPlayer): void {
  void player.seekTo(0).then(() => player.play()).catch(() => undefined);
}

export type AttendanceScanFeedbackController = Readonly<{
  muted: boolean;
  preferenceBusy: boolean;
  preferenceError: string | null;
  notify: (kind: AttendanceScanFeedbackKind) => void;
  toggleMuted: () => Promise<void>;
}>;

export function useAttendanceScanFeedback(): AttendanceScanFeedbackController {
  const successPlayer = useAudioPlayer(null, { updateInterval: 1_000 });
  const duplicatePlayer = useAudioPlayer(null, { updateInterval: 1_000 });
  const failurePlayer = useAudioPlayer(null, { updateInterval: 1_000 });
  const [muted, setMuted] = useState(true);
  const [preferenceBusy, setPreferenceBusy] = useState(true);
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [audioReady, setAudioReady] = useState(false);
  const preferenceLock = useRef(false);
  const preferenceLoaded = useRef(false);

  useEffect(() => {
    let active = true;
    Promise.all([
      SecureStore.getItemAsync(PREFERENCE_KEY, PREFERENCE_OPTIONS),
      setAudioModeAsync({
        allowsRecording: false,
        interruptionMode: 'mixWithOthers',
        playsInSilentMode: true,
        shouldPlayInBackground: false,
        shouldRouteThroughEarpiece: false,
      }).then(() => ensureSoundFiles()),
    ]).then(([preference, sources]) => {
      if (!active) return;
      successPlayer.replace(sources.success);
      duplicatePlayer.replace(sources.duplicate);
      failurePlayer.replace(sources.failure);
      if (!preferenceLoaded.current) {
        preferenceLoaded.current = true;
        setMuted(preference === 'muted');
      }
      setAudioReady(true);
    }).catch(() => {
      if (!active) return;
      // Audio is optional feedback. Haptics and visible status stay available,
      // and an unreadable preference never causes unexpected sound.
      if (!preferenceLoaded.current) setMuted(true);
      setPreferenceError('Scan sound is unavailable on this device.');
    }).finally(() => {
      if (active) setPreferenceBusy(false);
    });
    return () => {
      active = false;
    };
  }, [duplicatePlayer, failurePlayer, successPlayer]);

  const notify = useCallback((kind: AttendanceScanFeedbackKind) => {
    void Haptics.notificationAsync(hapticType(kind)).catch(() => undefined);
    if (muted || !audioReady) return;
    const soundKind = attendanceScanSoundKind(kind);
    if (soundKind === 'success') replay(successPlayer);
    else if (soundKind === 'duplicate') replay(duplicatePlayer);
    else replay(failurePlayer);
  }, [audioReady, duplicatePlayer, failurePlayer, muted, successPlayer]);

  const toggleMuted = useCallback(async () => {
    if (preferenceLock.current || preferenceBusy) return;
    preferenceLock.current = true;
    setPreferenceBusy(true);
    setPreferenceError(null);
    const nextMuted = !muted;
    try {
      await SecureStore.setItemAsync(
        PREFERENCE_KEY,
        nextMuted ? 'muted' : 'audible',
        PREFERENCE_OPTIONS,
      );
      setMuted(nextMuted);
    } catch {
      setPreferenceError('Sound preference was not saved. Try again.');
    } finally {
      preferenceLock.current = false;
      setPreferenceBusy(false);
    }
  }, [muted, preferenceBusy]);

  return { muted, preferenceBusy, preferenceError, notify, toggleMuted };
}
