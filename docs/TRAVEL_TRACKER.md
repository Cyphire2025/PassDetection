# Visa and flight tracker

The dashboard workspace is under **Operations → Documents → Visa / Flight Tracker**. Office users choose a client group and track visa applications and flight bookings independently. One row action, keyboard queue, pasted name list, spreadsheet preview, or filtered bulk action updates readiness without changing passport approval or document assignment.

The source is `client_groups` and its `passport_submissions`. Imported groups and public collection submissions use the same roster. Normal upload, extraction, review, failed, and approved states are all included. Active explicit rejection/replacement decisions use the existing `operational_roster_member()` rule, so displaced or removed records do not reappear. WhatsApp broadcast contacts do not create tracker passengers. Archived/deleted groups are outside this workspace, including for a platform administrator.

## Permissions and storage

The existing agency boundary and staff created/assigned-group scope apply to every query. Office roles are platform administrator, agency administrator, agency manager, and agency staff. A staff user gains no access merely by knowing a group UUID. The canonical MCP connection and Documents section permissions further restrict access to tracker tools; existing connections gain no write permission automatically.

Migration `0129_travel_tracker`, following `0128_mcp_document_delivery`, adds one table. `passenger_id` is the primary key; the composite foreign key binds it to its actual agency and client group. Visa and flight marks, timestamps, and actor IDs are separate columns. Existing passports, approvals, extraction revisions, collection links, and assigned documents are unchanged by a tracker write. Passenger deletion cascades its tracker row. The downgrade refuses to remove a nonempty tracker table; preserve/export tracking history before an intentional downgrade.

Writes revalidate the active office actor and lock the visible parent group before selecting passengers. A mixed valid/invalid ID request fails before any status changes. All changes and the integrity-chained audit event commit together. Repeating the same mark is idempotent. The group lock serializes tracker writes; it is not a general snapshot lock for every public collection writer. Filtered bulk updates compare the current matched count with `expected_count` and return `409` when it differs. An equal count alone does not prove identical historical membership. MCP authentication already holds a live owner permission fence and uses the service's internal `actor_already_fenced` option to avoid upgrading simultaneous owner SHARE locks. Its operation service uses `commit=False`, retaining tracker changes in the same transaction as the canonical idempotency receipt and audit record.

Authorized roster reads and matching previews record privacy-minimal sensitive-access events. Exports record their group, track, status filter, and row count; search text and passport/contact values are omitted from audit metadata. Responses carrying roster data or spreadsheets use `Cache-Control: no-store`.

## HTTP contracts

All routes are under `/api/v1/travel-tracker` and require existing dashboard authentication. Cookie-authenticated writes require the existing trusted-origin CSRF check. Spreadsheet preview performs no readiness mutation.

| Method and path | Inputs | Result |
| --- | --- | --- |
| `GET /groups` | `search`, `page`, `page_size` | `{groups, total, page, page_size}` with group trip details and `total`, `visa_marked`, `flight_marked` counts |
| `GET /groups/{group_id}` | `track=visa\|flight`, `status=all\|marked\|pending`, `search`, `page`, `page_size` | `{group, counts:{total,marked,pending}, passengers, total, page, page_size}`; counts cover the whole canonical group, while top-level total reflects the active search/status filter |
| `PATCH /groups/{group_id}/marks` | JSON described below | `{updated_count, unchanged_count, passenger_ids, counts}` |
| `GET /groups/{group_id}/export` | `track`, `status`, `search` | Downloadable `.xlsx` of the authorized matching roster |
| `POST /groups/{group_id}/import/preview` | Multipart `file`, `track`, `marked` | Row-by-row match review, counts, and unique safe `passenger_ids` for a subsequent mark request |

Mark explicit IDs in one atomic request:

```json
{"track":"visa","marked":true,"passenger_ids":["00000000-0000-0000-0000-000000000001"]}
```

Mark every passenger in a current server filter:

```json
{"track":"flight","marked":true,"selection":{"status":"pending","search":"Rao"},"expected_count":12}
```

Supply exactly one selection mode. `marked` is a JSON boolean, not a string. The preview returns `matched`, `ambiguous`, `unmatched`, and `duplicate` rows with reasons. Only the unique `matched` IDs are submitted to the regular mark endpoint, so the same authorization, existence validation, atomic transaction, attribution, and audit checks apply after review.

## Spreadsheet behavior and limits

Exports include passenger IDs, names, contact/trip details, submission status, both readiness flags and their attribution, family/qualifier details, the merged extracted/confirmed passport fields, imported staff metadata, and custom question/detail answers. Formula-leading untrusted strings are stored safely as text. IDs make an exported subset suitable for a later update preview. An empty filtered export remains a valid workbook with headers.

Preview accepts `.xlsx` with one sheet or UTF-8 `.csv`. Recognized identity headers include `Passenger ID`, `Submission ID`, `Name`, `Full Name`, `GIVEN NAME` plus `SURNAME`, and `Passport Number`. Legacy title rows are allowed before the header. The selected visa/flight track and mark/clear action apply uniformly to the reviewed match list; uploaded readiness columns do not silently change the requested action.

Matching uses the strongest supplied identifier: valid group-scoped passenger ID first, passport number next, then an exact unique normalized name. Unicode normalization, case, and whitespace are normalized; no fuzzy name matching occurs. A supplied ID or passport that fails to match does not fall back to a weaker name. A supplied ID conflicting with a supplied passport is rejected. Duplicate names/passports require a stronger identifier. Formula identity cells are rejected. Duplicate spreadsheet rows are reported and produce one update ID.

| Boundary | Limit |
| --- | --- |
| Dashboard group page | 100 groups |
| Dashboard roster page | 200 passengers |
| Search text | 160 characters |
| Explicit mark request / spreadsheet data rows | 1,000 |
| Filtered bulk action / export / group matching roster | 20,000 passengers |
| HTTP upload bytes | 8 MiB |
| Workbook expanded bytes / archive members | 32 MiB / 2,000 |
| Spreadsheet columns / input cell length | 256 / 2,048 characters |

Workbook parsing, malware scanning, spreadsheet matching, and export generation run outside the async event loop. Expansion, compression-ratio, macro, external-workbook-link, encryption, row, and column checks bound parser work. Invalid workbook XML returns a controlled input error. Files over the configured tracker upload limit return `413`; invalid contents/limits return `422`. MCP reuses the canonical native upload/export workflow and its deployment limits, documented in [MCP travel tracker access](architecture/travel-tracker-mcp.md).

## Release and verification

The reviewed additive release contract is `travel_tracker_additive_v1`, exactly `0128_mcp_document_delivery → 0129_travel_tracker`. It binds the migration source SHA, preserves every existing MCP setting/permission/grant/request, requires the new table to be empty before activation, retains old containers and artifacts, and forbids automatic downgrade. The existing writer-fenced retained executor validates a fresh backup before running `backend/scripts/release_travel_tracker_upgrade.py`; the helper verifies the existing migration owner, every historical row field, old schema and privileges, the exact tracker schema, and inherited passport runtime DML grants. It fails when the actual source is outside the reviewed contract. Preserve existing database/storage volumes and rehearse the upgrade on a synthetic/restored database under the normal release gates. The same-schema code updater cannot apply this migration.

Quick local commands from `backend`:

```powershell
.\.venv311\Scripts\python.exe -m pytest --no-cov tests\unit\presentation\test_travel_tracker.py tests\unit\infrastructure\test_travel_tracker_spreadsheets.py tests\unit\infrastructure\test_travel_tracker_migration.py
.\.venv311\Scripts\python.exe -m ruff check --no-fix app\infrastructure\travel_tracker app\infrastructure\database\travel_tracker_model.py app\presentation\api\v1\routes\travel_tracker.py app\presentation\api\v1\schemas\travel_tracker_schemas.py
.\.venv311\Scripts\python.exe -m mypy app\infrastructure\travel_tracker app\infrastructure\database\travel_tracker_model.py app\presentation\api\v1\schemas\travel_tracker_schemas.py app\presentation\api\v1\routes\travel_tracker.py
```

SQLite tests verify canonical roster coverage, explicit roster removals, tenant/staff/lifecycle scope, active actor revalidation, independent marks, idempotency, audit persistence, mixed-ID atomic failure, stale filtered counts, exact matching, duplicates, round-trip exports, formula safety, malformed workbook handling, and composite foreign-key enforcement. These checks do not establish PostgreSQL row-lock scheduling, real-service concurrency, populated production migration behavior, or a deployed release. The dedicated synthetic PostgreSQL service lane owns those contracts.
