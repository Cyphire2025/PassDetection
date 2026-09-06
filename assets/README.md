# Shared project assets

Use this folder as the central library for reusable PassDetection artwork, branding and media masters.

## Global Connect branding

| Asset | Description |
| --- | --- |
| [4K logo animation](branding/global-connect/global-connect-logo-reveal-4k.mp4) | 3840 × 2160, 60 fps, 9 seconds, H.264 MP4 with stereo AAC sound and a white background |
| [Original company logo](branding/global-connect/global-connect-logo-original.jpeg) | Supplied original JPEG, preserved without modification |
| [Animation poster](branding/global-connect/global-connect-logo-reveal-poster.png) | 1920 × 1080 PNG of the completed logo composition |
| [Company journey film](branding/global-connect/journey-film/README.md) | The login experience: a seamless motion film about corporate travel, destination hospitality and conferences, with editable source and delivery exports |
| [Transparent company logo](branding/global-connect/globalconnect-logo-removebg-preview.png) | Supplied PNG from the project root, preserved without modification |
| [Login background artwork](branding/global-connect/login-background/README.md) | A sculptural aviation form for the navy panel and fine travel engraving for the white panel, with editable SVG source |
| [Processing motion](branding/global-connect/processing-motion/README.md) | Distinct passport extraction, document analysis, renaming and distribution scenes, with a standalone animated preview |
| [WhatsApp broadcast motion](branding/global-connect/broadcast-motion/README.md) | Welcome, passport-link and reminder dispatch scenes for the composer, live progress and floating tracker, with editable source and an interactive preview |

The animation assembles the globe, lettering and flight-path swooshes, then holds on the original logo. The 4K master and supporting images were copied from the finished logo animation package and verified using SHA-256 checksums.

## Organization

- `branding/<brand>/`: company logos, brand animations and their supporting files.
- `images/`: shared photographs and illustrations, grouped by purpose when added.
- `icons/`: shared icon source files when added.
- `audio/`: reusable sound assets when added.
- `video/`: other project video masters when added.
- `fonts/`: font files and their license information when added.

Create additional folders when assets are added. Use descriptive lowercase filenames with hyphens, and include resolution or version when needed. Keep source artwork separate from optimized exports and document any asset usage restrictions alongside the file.

The web app currently serves runtime assets from `frontend/public/`, and the mobile app bundles runtime assets from `mobile/assets/`. Prepare appropriately sized copies there when integrating a shared asset into an application. This library is for reusable project assets; passenger uploads, private operational documents, credentials and temporary generated files belong outside it.
