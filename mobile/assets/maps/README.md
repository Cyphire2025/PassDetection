# Offline globe geography

`earth-land.png` is an equirectangular reference mask rasterized from the repository's
`assets/branding/global-connect/journey-film/source/ne_110m_land.geojson`.

Source: [Natural Earth 1:110m physical land](https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/).
Natural Earth data is [public domain](https://www.naturalearthdata.com/about/terms-of-use/).
Rebuild with `python mobile/scripts/build-earth-land-texture.py` (Pillow required).

The renderer imports `earth-land-mask.json` from the JavaScript bundle. It contains
the exact same 2048 x 1024 grayscale pixels as the PNG, losslessly run-length
encoded: each run is one value byte and a big-endian unsigned 16-bit count, stored
as base64 (`rle8-v1`). Both files are regenerated together by the script above.
The decoded mask is shared by the card and expanded view; there is no filesystem
cache, Android drawable decoding, PNG decoder, or network dependency at runtime.

Each GL context uploads explicit opaque RGBA bytes, fits the driver's texture
limit if needed, then checks texture completeness and reads one land and one
ocean texel before reporting ready. The readback runs only during initialization,
never during flight animation or globe gestures. Initialization failures retain
the existing readable route details and globe placeholder.

The map is decorative geographic context, not a navigational chart or a statement
of political boundaries. Coastlines are generalized at 1:110m; small islands may
not appear. Route markers use resolved destination coordinates, independently of the
land mask. No maps API, map token, live location, or network texture fetch is used.
