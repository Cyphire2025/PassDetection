# Passenger journey globe

The selected passenger trip owns the destination card and its expanding globe.
The card uses a muted shaded Earth with a raised route and animated aircraft;
the full-screen view supports drag, pinch, bounded 1–2.4× zoom, and route reset.
The earth pixels are bundled, so rendering never requests map tiles or decodes
an Android image resource. See `mobile/assets/maps/README.md` for regeneration.

## Destination behavior

- Departure is New Delhi, India.
- Normal builds call the authenticated `/mobile/trips/{id}/journey-destination`
  endpoint. The server reads the authorized group's saved destination; the
  client never supplies arbitrary lookup text or another passenger's identity.
- The server geocodes a country, state, or city through a configurable Photon
  endpoint and caches the result by normalized place. A country or state stays
  that geographic place; it does not silently become an arrival airport.
- For otherwise ambiguous bare city names, the backend can use Photon's OSM-linked
  importance metadata when one city has both high prominence and a clear lead.
  Qualified destinations retain their specified country/state. Missing or weak
  evidence still yields ambiguity. Resolver policy v3 bypasses old result caches.
- The in-memory mobile query is scoped by account, trip ID, and destination.
  A changed destination cannot reuse the old query's marker. Temporary lookup
  contention gets at most two delayed retries, honoring server backoff.
- Pull-to-refresh explicitly invalidates the selected account/trip/destination
  lookup, including a recent ambiguous result. An inactive card refetches when
  visible again; another account's or destination's cache is not invalidated.
- An unavailable or ambiguous lookup leaves the globe interactive without
  inventing an endpoint. The details explain its current state.
- The explicitly isolated emulator demo uses the local destination catalog and
  never calls the backend. This is a visual fixture, not proof of production
  provider configuration or passenger authorization.
- Routes and distances are illustrative great-circle geography, not booked
  flight segments, schedules, or live aircraft tracking. OSM attribution appears
  alongside online-resolved route details.

## Lifecycle and accessibility

Animation pauses when the card is scrolled away, the trip tab loses focus, a
modal covers the card, or the app backgrounds. Reduced-motion preference freezes
aircraft motion and removes expansion timing. The expanded view also offers
labelled buttons for zoom/reset and supports Android Back. Native GL failures
retain readable route details and a working close control.

Each GL context uploads explicit RGBA geography pixels and verifies texture
completeness plus land/ocean pixel readback before reporting ready. Failed or
empty uploads retain the fallback instead of showing a successfully loaded but
empty sphere. Decoded grayscale data is shared; upload/readback runs only on
context creation, never during aircraft or camera animation.

Android release minification must preserve Expo GLView's reflected constructor;
the registered `with-expo-headless-loader-proguard` plugin installs that narrow
rule during prebuild. Its test covers upgrading previously generated projects.

## Verification

Run the feature's Jest suites for route mapping, API parsing, query/account
boundaries, geometry, offline geography, GPU upload contracts, fallback states,
and controls. Native GPU appearance,
gesture behavior, expansion, and release startup require emulator/device checks;
JavaScript mocks do not establish those results. iOS device validation is a
separate check.
