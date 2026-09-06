# Global Connect Travels — Journey Pavilion

An original 24-second corporate-travel motion film created for the PassDetection login page. The art direction follows Global Connect Travels' current positioning: corporate journeys, hospitality, MICE and event experiences. It is a continuous illustrated scene, not a logo reveal.

## Deliverables

- `journey-film-web.mp4`: silent H.264, 1600 × 1000, 30 fps, 24 seconds, fast-start playback.
- `journey-film-poster.jpg`: matching opening frame, 1600 × 1000.
- `journey-film-master.mp4`: matching high-resolution master, 3200 × 2000, 60 fps.
- `journey-film-4k.mp4`: native-rendered UHD master, 3840 × 2160, 30 fps. The full 8:5 artwork is rendered directly at 3456 × 2160 and centered between two 192-pixel navy margins. It is not an upscale of another export and nothing is cropped.
- `qa/contact-sheet.jpg`: six representative frames.
- `source/scene.cjs`: editable geometry, lighting, camera, animation and palette.
- `source/render.cjs`: deterministic still/video renderer.
- `source/ne_110m_land.geojson`: public-domain geographic source geometry.

The web export and poster are also stored in `frontend/public/assets/branding/global-connect/journey-film/` for local app delivery. Both high-resolution masters stay in the project asset library.

## Direction and timing

The globe is textured with accurate land shapes and lit as a spherical surface. An original swept-wing aircraft follows its orbital path. The same sculptural platform becomes a hospitality campus with roof terraces and guests, then a conference venue with a moving stage visual and a seated audience. The world returns to the opening arrangement for a seamless loop.

The platform uses a brighter, desaturated slate/silver face, shaded slate sidewall, a cool ivory rim, and restrained fine etching for stronger separation from the blue globe. The smaller welcome-globe pedestal uses the same silver material family. The navy background, globe palette and 24-second timing remain unchanged.

The current scene revision gives the hotel 18% more width and vertical presence and the conference 20%, with eased transitions and restrained depth expansion to retain complete visibility on the shared plate. The standalone globe's size and position are unchanged; its small contextual counterpart moves slightly left to make room for the larger architecture. The silver base now includes three layered rim bands, fourteen recessed rim segments, fine radial compass ticks, subtle annular material inlays, an engraved compass rose and three inset navigation waypoints. These are physical graphic details without text, blur, glow or particle effects.

| Time | Scene |
| --- | --- |
| 0–5.6 seconds | Global journey: rotating globe and aircraft |
| 5.6–7.6 seconds | Transition into destination and hospitality |
| 7.6–12 seconds | Hotel campus, glazed architecture, planted terraces, guests |
| 12.3–14.4 seconds | Architecture transitions into an event venue |
| 14.4–19 seconds | Conference stage, presenters and coordinated audience |
| 19–21.5 seconds | Venue folds back into the global journey |
| 21.5–24 seconds | Globe and aircraft, reconnecting to frame zero |

For coarse UI chapter indicators, use global before 6.5 seconds, hospitality from 6.5 to 13 seconds, events from 13 to 20 seconds, then global again.

The uncompressed scene's outer edge color is `#0b2239`. MP4 exports use full-range H.264 with explicit BT.709 primaries and matrix, plus the sRGB (`iec61966-2-1`) transfer characteristic. These tags are set on frames through FFmpeg `setparams` as well as in output metadata. This matters: an otherwise identical full-range clip with unspecified transfer/primaries showed a dark rectangle in the Windows browser, despite close RGB agreement in FFmpeg's decoder. Four browser probes were compared; the fully tagged sRGB variant removed the severe mismatch. Minor codec/display differences remain possible. Palette: navy, blue, cool ivory, restrained lime, and small warm hospitality accents. The renderer uses surface shading and crisp geometry, without blur, depth of field, haze, artificial grain or particle effects. All visible motion is generated from the scene: sphere rotation, aircraft travel, camera yaw, spatial scaling, architectural assembly and attendee movement. No external font or runtime service is required to play the video.

## Provenance and source references

- Company positioning: https://gctravels.in/ and https://gctravels.in/about/ (reviewed 6 September 2026).
- Geographic data: Natural Earth 1:110m land, https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson . The downloaded data file is included with the editable source.
- Natural Earth identifies its map data as public domain: https://www.naturalearthdata.com/about/terms-of-use/ . Geographic data is used without political borders or geographic labels.
- Aircraft, buildings, stage, furniture, people, paving and animation were created specifically for this film in source code. No third-party photographs, videos, logo-reveal frames, music or generated still images are used.

## Re-render

Requires Node.js, `@napi-rs/canvas` 0.1.100, and FFmpeg with `libx264`. Install the dependency inside `source/`, or set `NODE_PATH` to an existing directory containing it. Set `FFMPEG_PATH` to your FFmpeg executable if it is not on `PATH`.

```powershell
node source/render.cjs --stills
node source/render.cjs
$env:SPHERE_SIZE = '1120'
node source/render.cjs --width 3200 --height 2000 --fps 60 --crf 18 --output journey-film-master.mp4
$env:SPHERE_SIZE = '1216'
node source/render.cjs --width 3840 --height 2160 --fps 30 --crf 18 --contain --output journey-film-4k.mp4
```

The renderer takes exact times rather than browser playback captures. `render(0)` and `render(24)` are the same scene by construction; the last encoded frame is one normal frame before the first, preserving the motion interval at the loop boundary.

## Export verification

All three current MP4 files were freshly rendered from the revised scene source and decoded end to end by FFmpeg without errors. The web export contains 720 frames at 30 fps (2,078,001 bytes); the 3200 × 2000 master contains 1,440 frames at 60 fps (10,403,574 bytes); the native UHD export contains 720 frames at 30 fps (8,894,517 bytes). All are exactly 24 seconds and contain only a video stream. Their MP4 metadata precedes the media payload for fast-start playback. All current exports set their explicit sRGB/BT.709 frame tags directly in the source renderer.

The UHD scene is rendered at 3456 × 2160 inside its 3840 × 2160 canvas, with no image scaling during placement. Its shaded sphere is rendered at 1216 × 1216, exceeding the approximately 1201-pixel diameter displayed in the scene. The encoded opening frame was inspected visually to verify sharpness, generous margins and complete visibility.

The opening scene and its mathematical 24-second endpoint are pixel-identical. At 800 × 500, the average RGB change across the encoded-loop timing boundary is 0.345, compared with 0.337 for an ordinary first-frame step. This confirms the intended scene continuity rather than a frozen hold or dissolve. A decoded web corner measures RGB (10, 34, 56), within one channel value of the intended navy background. The public web copy matches the source asset's SHA-256 checksum.

Frame-count metadata, background/copy verification, loop comparison and SHA-256 manifests are recorded in `qa/`. The four temporary browser color probes are preserved in `qa/browser-color-probes/` and were removed from the app's public directory after selection. Browser integration and login behavior are verified separately by the application implementation.
