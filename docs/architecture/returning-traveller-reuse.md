# Companies and retained traveller evidence

This is a local implementation architecture record for the October 2026 feature. The user's later decisions supersede the original attached implementation prompt: versions have no automatic age purge; future reuse requires explicit recorded authority; WhatsApp proof uses OTP plus full passport, passport proof uses full passport plus a reliable saved date, and individual-code proof uses code plus full passport. The latter two routes have no routine OTP. These checks do not prove legal ownership, guardianship or delegation.

## Boundaries and records

The canonical company is `client_groups.company_id`. The existing organization directory is reused; GC App enablement is independent. Each new claim checks current group, organization and policy revisions. Deactivation, group reassignment and reuse-policy changes invalidate previous authority. Historical records keep their original company even when a populated group's current company changes.

`TravellerProfileModel` identifies one retained person in one agency/company. Passport identities, accepted field revisions, original assets, identifiers, contact bindings and trip participations are separate records. Composite foreign keys enforce person, document, agency and company consistency. Neither a name nor a phone is a unique person key. Contacts can be shared, changed or historical without changing somebody else's person record.

Secrets and dates used as proof never become URL parameters. Proof tokens are stored as hashes. Identifier fingerprints use independent keyed digests with agency/company scope; encrypted fields use separately configured encryption material. Configuration defaults to disclosure disabled. An absent key, unknown key version, missing accepted provenance or absent permission fails closed. Identity authorization does not use an application cache.

Claims retain attempts, selected reliable date fields, stable person selection and expiry across HTTP requests. Grants bind the exact claim, selected person, original proof document, group and authoritative revisions. Current history can select the newest accepted default document independently of the passport used to identify the person. Each asset request performs live authorization and ownership checks before returning bytes.

## Historical recognition, enrollment and renewal

Recognition runs through durable jobs, at most 100 source rows per transaction. An exact scoped passport/context match or a configured individual code can propose a match. Names and shared phone numbers cannot merge people. Conflicting strong identifiers or multiple people are review cases. A case never creates permission, a participation, a verified contact or a retained identity automatically.

Sources include operational passport submissions and the group's linked WhatsApp recipient and rejected-contact rows. Shared-phone delivery consolidation does not collapse those saved people. Cursor state includes source kind and UUID; each of the three query branches admits at most 101 rows before the final sort. Previously truncated imports cannot be reconstructed automatically, so matching coverage explicitly means durable saved rows. Imported passport text is not trusted accepted evidence.

Staff resolution creates only a pending current-trip membership. It rechecks the exact scoped source, source revision, a keyed fingerprint of content and displayed roster identity, and the group/configuration/key revisions and individual identifier semantics. Stale cases require a new preview. New previews may refresh unresolved cases but preserve recorded human resolutions and separately authorized replacement associations.

Explicit staff enrollment requires a current accepted source revision, enabled configured purpose/notice/processing basis, permission evidence and expected group revision. Existing-person updates also require the expected profile revision. Missing issuer/type must be attested by the reviewer after viewing the source; nationality and place of issue are never substituted. Enrollment records the actor, attestation, source revision and immutable provenance. An HMAC of the complete request binds retry idempotency to its original payload.

A renewal creates another passport identity for the same reviewed person. Lost, cancelled, compromised, disputed and rejected identities cannot be reactivated by uploading another scan. A later accepted issue date may replace the default for future trips. Existing accepted participation references remain frozen.

A public replacement is a provisional association: a live reviewed grant, exact group, unchanged review version and the upload's own secret capability are all required. The submitted UUID alone conveys no authority. A digest binds confirmed source fields and all source image keys. Normal staff approval may increment its extraction revision without changing content; edited fields/images require a renewed association. Staff must subsequently accept the source and acknowledge the selected traveller during explicit enrollment. No public replacement route approves retained evidence.

## Independent storage and current-trip authority

Enrollment stages private asset-copy intents in the same transaction as the accepted revision. Workers use server-side object copy and stat calls, so no document body is loaded into the worker. Originals, covers, photo and derived images remain distinct. Allowed copied media are JPEG, PNG, WebP and PDF, at most 20 MiB each. The same availability policy is used by review, delivery and reuse publication.

Copies recheck source tenant/status/extraction/content-key linkage, profile permission evidence, retention authority and accepted revision before and after I/O. A destination is published only after size, MIME and optional checksum validation. A MIME-derived allowlisted suffix is persisted before copying, and its media type remains stable across retries. There are at most two globally admitted PostgreSQL copy leases, five attempts and bounded retry delays. A timeout retains the lease for the configured provider timeout envelope because cancelling an async wait cannot stop an already running storage SDK thread. Destination keys are stable across retries.

Successful reuse produces a normal current-group submission and a versioned participation referencing independent retained assets. Staff image authorization additionally checks exact submission, group, participation, person and document ownership. Cached thumbnails and derived staff views are reached only after that check. Retained objects do not receive reusable presigned URLs from the normal public response helper.

Future-reuse withdrawal and current-trip retention are distinct. Withdrawal immediately invalidates future history access. A lawful submitted/accepted current-trip snapshot keeps its referenced asset until that operational source is removed. Explicit asset purge or hard profile deletion denies retained reads immediately. The bounded deletion worker removes unreferenced withdrawn assets and respects in-flight copy leases. Existing group cleanup, bulk deletion and image replacement cannot remove independently retained originals. Operational source links are detached before deletion; immutable provenance remains.

## Complexity and resource bounds

| Operation | Query/application bound | Primary access path |
| --- | --- | --- |
| Exact passport lookup | Indexed seek, at most two candidates, O(1) application memory | agency/company/key version/fingerprint |
| Shared-phone candidates | Bounded candidate list, no family-history expansion | scoped contact fingerprint and current status |
| Staff source page | At most 51 rows plus at most 50 candidate projections | agency/group/UUID seek; existing trigram search expression |
| Reconciliation page | At most 303 source rows before bounded sort; at most 100 cases; two aggregate match lookups | scoped source UUID seek and identity indexes |
| Staff match resolution | One exact source plus configuration lookup; O(1) application rows | source primary key and scoped link; source-only row lock |
| Copy | At most two active leases; no whole-document buffer | pending/due asset and lease indexes |
| Staff approval sync | O(ceil(n/100)) queries and O(min(n,100)) rows | participation source-submission index |
| Current snapshot read | One retained-asset seek plus bounded exact participation existence | object key, document revision, source submission |
| Withdrawal tick | At most 100 assets; current-trip reference existence check | permission and asset owner/state indexes |

PostgreSQL locking and index plans require service-environment qualification. SQLite tests establish scoped query shape, constraints and rollback behavior, not PostgreSQL isolation or production throughput. Additional service boundaries, partitioning and replicas have not been introduced without measured need.

## Evidence and limits

The reproducible local benchmark is `backend/scripts/benchmark_traveller_queries.py`. The 120.03-second receipt at `docs/implementation/companies-reuse-evidence/capacity-100000-profiles-200000-participations.json` used 100,000 profiles, 100,000 passports, 200,000 participations, 250 companies and four concurrent SQLite readers. It recorded zero errors and 113,246,208 peak working-set bytes. Query p95 was 1.814 ms for company search, 0.280 ms for exact passport lookup, 2.198 ms for a traveller page and 2.676 ms for group summary. These are local query timings, not HTTP latencies. One million users/participations, production API concurrency, object-store recovery under real network faults, PostgreSQL locks and production tenancy distribution remain unqualified.
