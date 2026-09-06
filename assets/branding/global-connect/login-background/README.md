# Login background artwork

Original SVG artwork for the Global Connect login, designed to remain crisp at any screen size.

- `wing-architecture.svg`: the current navy-panel artwork. A single swept aviation form uses broad blue surfaces, a layered leading edge, a folded return and a small green inlay. It contains no map, surface pattern, blur or animation.
- `paper-routes.svg`: fine curved engraving and a small compass detail for the white sign-in panel. The central form area remains clear.
- `travel-atlas.svg`: the previous, unused navy-panel design, retained as a source reference. Its decorative connections do not assert company offices or specific destinations served.
- `source/generate-backgrounds.cjs`: editable, deterministic Node.js generator for `travel-atlas.svg` and `paper-routes.svg`. The wing artwork is edited directly as SVG.

Matching SVG copies are stored in `frontend/public/assets/branding/global-connect/login-background/` for application delivery. CSS controls their placement. The former atlas and contour design is no longer rendered on the navy panel. The approved white-panel artwork and styling were preserved exactly during the wing revision.

Land outlines come from the public-domain Natural Earth source already included in `../journey-film/source/ne_110m_land.geojson`. There are no political boundaries or geographic labels. Natural Earth terms: https://www.naturalearthdata.com/about/terms-of-use/ .

The only displayed logo is the supplied transparent `globalconnect-logo-removebg-preview.png`. Its 612 × 408 source has visible artwork in the 417 × 145 rectangle starting at (103, 145). CSS removes the empty outer margins without modifying the source pixels, stretching the image or adding a backing. Its width is 210 pixels on desktop, 190 on shorter desktop viewports and 165 on compact desktop viewports. The header retains its previous height so the headline and film positions remain steady.

The headline accent is `#a9d94b`, a brighter, saturated version of the green in the original company logo. The transparent PNG supplied by the user is a different palette variant with more yellow in its lettering; its original colors are preserved.
