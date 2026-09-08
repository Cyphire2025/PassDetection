import { isDevice } from 'expo-device';
import { useVideoPlayer, VideoView } from 'expo-video';
import { useCallback, useEffect, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { LaunchAlphaMotion } from './launch-alpha-motion';

const launchVideo = require('../../../assets/videos/global-connect-launch-4k.mp4') as number;
const compatibleVideo = require('../../../assets/videos/global-connect-launch-compatible.mp4') as number;

type LaunchVideoProps = {
  playing: boolean;
  onComplete: () => void;
};

/** The bundled asset itself ends at 5.000 seconds; the player never loops. */
export function LaunchVideo(props: LaunchVideoProps) {
  return Platform.OS === 'android' && Number(Platform.Version) < 29
    ? <LaunchAlphaMotion {...props} />
    : <NativeLaunchVideo {...props} />;
}

function NativeLaunchVideo({ playing, onComplete }: LaunchVideoProps) {
  // Software decoders in simulators cannot reliably play the 4K/60 master.
  // Physical devices try it first, with the same five-second cut as fallback.
  const [compatible, setCompatible] = useState(() => !isDevice);
  const handleUnavailable = useCallback(() => {
    if (compatible) onComplete();
    else setCompatible(true);
  }, [compatible, onComplete]);

  return (
    <LaunchVideoPlayer
      key={compatible ? 'compatible' : '4k'}
      source={compatible ? compatibleVideo : launchVideo}
      playing={playing}
      onComplete={onComplete}
      onUnavailable={handleUnavailable}
    />
  );
}

function LaunchVideoPlayer({ playing, onComplete, onUnavailable, source }: LaunchVideoProps & {
  source: number;
  onUnavailable: () => void;
}) {
  const [firstFrameVisible, setFirstFrameVisible] = useState(false);
  const player = useVideoPlayer(source, (instance) => {
    instance.loop = false;
    instance.muted = true;
    instance.volume = 0;
    instance.audioMixingMode = 'mixWithOthers';
    instance.allowsExternalPlayback = false;
    instance.showNowPlayingNotification = false;
    instance.staysActiveInBackground = false;
  });

  useEffect(() => {
    const finished = player.addListener('playToEnd', onComplete);
    const status = player.addListener('statusChange', ({ status: nextStatus }) => {
      if (nextStatus === 'error') onUnavailable();
    });
    if (player.status === 'error') onUnavailable();
    return () => {
      finished.remove();
      status.remove();
    };
  }, [onComplete, onUnavailable, player]);

  useEffect(() => {
    try {
      if (playing) player.play();
      else player.pause();
    } catch {
      onUnavailable();
    }
  }, [onUnavailable, player, playing]);

  // A slow/unsupported decoder must not strand the user on the launch screen.
  // A separate end event is authoritative during normal playback.
  useEffect(() => {
    if (!playing) return;
    const timer = setTimeout(firstFrameVisible ? onComplete : onUnavailable, firstFrameVisible ? 6_000 : 2_500);
    return () => clearTimeout(timer);
  }, [firstFrameVisible, onComplete, onUnavailable, playing]);

  return (
    <View style={styles.fill}>
      <VideoView
        testID="launch-video"
        player={player}
        style={styles.fill}
        contentFit="contain"
        surfaceType="textureView"
        nativeControls={false}
        fullscreenOptions={{ enable: false }}
        allowsPictureInPicture={false}
        allowsVideoFrameAnalysis={false}
        playsInline
        useExoShutter={false}
        onFirstFrameRender={() => setFirstFrameVisible(true)}
      />
      {!firstFrameVisible ? <View pointerEvents="none" style={styles.cover} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { ...StyleSheet.absoluteFill, backgroundColor: '#FFFFFF' },
  cover: { ...StyleSheet.absoluteFill, backgroundColor: '#FFFFFF' },
});
