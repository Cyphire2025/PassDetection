# Global Connect mobile launch animation

`global-connect-launch-4k.mp4` is the first **5.000 seconds** of the existing company logo reveal at `assets/branding/global-connect/global-connect-logo-reveal-4k.mp4`. The shared nine-second master remains unchanged.

| Asset | Format | Size |
| --- | --- | --- |
| `global-connect-launch-4k.mp4` | 3840 × 2160, 60 fps, 300 frames, H.264 High / yuv420p, silent MP4 | 1,278,965 bytes |
| `global-connect-launch-compatible.mp4` | 1920 × 1080, 30 fps, 150 frames, H.264 High Level 4.0 / yuv420p, silent MP4 | 432,366 bytes |
| `../images/global-connect-launch-poster.png` | 3840 × 2160 PNG; final included frame at 4.9833 seconds | 583,836 bytes |
| `../images/global-connect-launch-first-frame.png` | 3840 × 2160 PNG; exact first frame, uniformly white | 29,472 bytes |
| `../images/global-connect-launch-logo-alpha.png` | 3840 × 2160 RGBA PNG; final frame for the moving and header logo | 637,931 bytes |
| `global-connect-launch-alpha.webp` | 960 × 540 lossless RGBA, 150 frames, 5,000 ms, one play; Android 8/9 fallback | 4,663,390 bytes |

The video is bundled locally and has its MP4 index before the media payload (`faststart`). It contains no audio track. The poster is decoded from the mobile export so the held frame matches the end of playback.

The three named launch PNGs have a separate, tested 1.25 MiB combined encoded-size budget and exact 3840 × 2160 dimensions. Their individual ceilings are 32 KiB for the blank first frame, 600 KiB for the held poster, and 640 KiB for the alpha logo. Ordinary app images retain the existing 4 MiB combined, 1,750,000-byte single-image, and 1,750,000-pixel decode ceilings; the total PNG count still includes launch images. Only these three exact filenames receive the launch allowance. A full-resolution RGBA decode can occupy approximately 31.6 MiB per still, so this source-size check does not replace native startup-memory profiling.

The 4K version remains the default launch asset. The compatible export is derived directly from that five-second video, preserving its complete 16:9 composition and timing while reducing decoder requirements. It supports the runtime fallback for devices that cannot decode 4K at 60 fps; this limitation was observed with the Android emulator's `c2.goldfish` decoder. It is not a replacement for the shared master or the default 4K asset.

## Composition

Use the same `ScreenBackdrop` wallpaper and gradient as the destination, with a centered 16:9 frame and `contain` fitting. Preserve the full composition instead of filling a portrait screen with a cropped video. The completed logo is already centered: its visible bounds are approximately x = 14.4–85.6% and y = 28.0–71.9% of the frame. The artwork has not been redesigned.

## App integration

`src/core/startup/app-launch-gate.tsx` owns the native-splash handoff and keeps the root navigator mounted while startup runs. `launch-video.tsx` plays the local MP4 once with `contain` fitting, no controls, no audio, no Picture in Picture and no background playback. The 16:9 artwork is centered over the shared wallpaper, with a maximum frame width of 720 layout units on tablets. The alpha final poster loads during the animation and remains if session bootstrap takes longer than five seconds.

On the welcome page, `LaunchLogoAnchor` measures the stationary 142 × 48 header slot in window coordinates. `launch-geometry.ts` subtracts the launch root's position and fits the visible artwork bounds rather than the padded video rectangle. After the last video frame and bootstrap readiness, there is a 160 ms hold, then a 1,050 ms native-driven sequence: the logo travels and shrinks into that slot while the hero panel and controls rise by 96 layout units with staggered opacity. The moving logo and static header use the same alpha final frame. The header stays hidden until completion. The rising panels use grouped alpha compositing during the transition so their overlapping surfaces fade evenly; the temporary Android hardware layers are released afterward. Other destinations retain a 650 ms crossfade. Missing or offscreen target measurements have a bounded 650 ms layout wait before fallback.

The page stays inaccessible to touch and accessibility focus until completion. Reduced motion and backgrounding settle immediately; returning to the app does not replay the sequence. Cleanup cancels pending animations without a late interactive callback.

On iOS and Android 10+, the outer video artwork wrapper uses native multiply compositing as a direct child of the isolated root containing `ScreenBackdrop`, so the white matte becomes the existing wallpaper. Android 8/9 lacks this native blend mode, so `LaunchAlphaMotion` plays the transparent animated WebP with the same five-second timeline. Its timer preserves remaining duration across a temporary inactive pause. The PNG and WebP use white-to-alpha unmatting; recompositing over white reproduces the original sampled RGB pixels exactly. The original MP4s remain unchanged.

The gate sits outside the app's SafeAreaProvider so initial inset measurement cannot prevent it from mounting. `native-splash.ts` also arms a 1.5-second native handoff fallback at root module initialization, outside React/provider rendering; the normal laid-out gate cancels it. This prevents the native splash and initial layout from waiting on each other. The video starts from the beginning after the stage is ready.

System reduced motion, decoder failure, missing first frame and playback stalls have bounded fallback paths. Leaving the app during the intro completes it; foregrounding an existing session does not replay it. Existing auth, deep-link and background cleanup paths continue underneath.

This adds the Expo SDK 57-compatible `expo-video` native module and changes native splash configuration. Android and iOS **must be rebuilt** through the project's normal native preparation/build flow before installed apps receive it; an old binary or a JavaScript-only update does not contain the new native module. `runtimeVersion` continues to use Expo's fingerprint policy.

Local verification for the docking transition covers 72 focused React Native tests across seven suites, TypeScript, and ESLint. After the final panel-compositing refinement, all 37 startup-gate tests, TypeScript, and focused ESLint passed again. A signed x86_64 Android build was installed on the Pixel_10_Pro emulator (API 37). Its final cold-launch recording, `launch-20260907-003037.mp4`, shows the reveal over the travel wallpaper, the completed logo holding and docking into the header, and the panels rising with evenly composited fades. The app remained alive with an empty crash buffer. The APK was verified to contain both exact MP4s and the alpha PNG/WebP; its packaged Hermes bundle matches the build, and source-map contents match the current gate and nine additional changed startup/UI modules. This verifies the Android emulator sequence; physical-device 4K playback, Android 8/9 fallback playback, and native iOS playback remain unverified. Local evidence is stored in `outputs/mobile-launch-qa/` at the repository root.

## Reproduce

Run from the repository root using FFmpeg with libx264. The export was made with FFmpeg 7.1 (libavcodec 61.19.100, libavformat 61.7.100), from the `imageio-ffmpeg` 0.6.0 Windows wheel. The tooling is temporary and is not a mobile dependency.

```powershell
ffmpeg -hide_banner -y -i assets/branding/global-connect/global-connect-logo-reveal-4k.mp4 -map 0:v:0 -an -frames:v 300 -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p -color_range tv -colorspace bt709 -movflags +faststart -metadata "title=Global Connect | Mobile Launch | First 5 Seconds" mobile/assets/videos/global-connect-launch-4k.mp4

ffmpeg -hide_banner -y -i mobile/assets/videos/global-connect-launch-4k.mp4 -vf "select='eq(n,299)'" -frames:v 1 -update 1 mobile/assets/images/global-connect-launch-poster.png

ffmpeg -hide_banner -y -i mobile/assets/videos/global-connect-launch-4k.mp4 -frames:v 1 -update 1 mobile/assets/images/global-connect-launch-first-frame.png

ffmpeg -hide_banner -y -i mobile/assets/videos/global-connect-launch-4k.mp4 -map 0:v:0 -an -vf "scale=1920:1080:flags=lanczos,fps=30" -frames:v 150 -c:v libx264 -preset slow -crf 16 -profile:v high -level:v 4.0 -pix_fmt yuv420p -color_range tv -colorspace bt709 -movflags +faststart -metadata "title=Global Connect | Mobile Launch | Compatible 1080p" mobile/assets/videos/global-connect-launch-compatible.mp4
```

The frame limit includes source frames 0 through 299 and ends at 5.000 seconds. It does not retime the reveal. Full decoding verified 300 frames, 3840 × 2160 resolution, 60 fps, five-second duration and no audio stream. MP4 box inspection verified that `moov` precedes `mdat`. The first frame was checked to be uniformly RGB (255, 255, 255).

The compatibility derivative also passed complete decoding: 150 frames, 1920 × 1080, 30 fps, 5.000-second duration and no audio stream. Its `moov` box precedes `mdat`. Producing it did not change the 4K asset's SHA-256.

## SHA-256 provenance

```text
Shared original master:
590488246b94d8fe31722d23a84eae0d55d0ec690bfb764754de666af2e8aa42

Mobile five-second video:
f1be5ad4bf533fab62293bc3f8d922f7a8fc377815fa5f451e1b7d2e1ac5c2a5

Compatible five-second video:
f54be29ef86384dbcc8bd289ba1a297f397c2cd767add3ff2b7ec146af5bd39e

Final-frame poster:
b65dcfb62f71b22ebc8ae14151d81ee1b9ab5ab7ec0daef201cdad8c63b6c413

First-frame native launch image:
1e517533d8afd7a51471666effa0d8f3a0999661b55f4431b042bec255dd2041

Transparent final-frame/header logo:
3f74b430c2ed3b83b822a7a8a8f8ba9ceb1c98a4358454f9cdee489b3646311b

Transparent five-second Android 8/9 animation:
5091b84e7087522557809cc330f4d54183d084065c4a49b31d585675c1f1b679
```
