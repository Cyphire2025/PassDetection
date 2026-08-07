# Document distribution lanes and PDF pipeline

This document defines the compatibility contract for passenger document
distribution. The persisted lane identifiers are stable data, not UI copy.

## Lane contract

| Persisted type | Family | Scope | Journey |
| --- | --- | --- | --- |
| `visa` | Visa | - | - |
| `flight_ticket` | Flight Tickets | International | Onward |
| `flight_ticket_arrival` | Flight Tickets | International | Return |
| `flight_ticket_domestic` | Flight Tickets | Domestic | Onward |
| `flight_ticket_domestic_arrival` | Flight Tickets | Domestic | Return |

The two original ticket values remain International lanes. A release must not
rename rows, copy objects, or rewrite storage keys to express the new UI
hierarchy. Migration `0080_domestic_ticket_lanes` only widens the resumable
upload-receipt check constraint; Domestic starts empty because its identifiers
are additive.

Backend semantics live in
`app/domain/value_objects/travel_document_taxonomy.py`. Frontend labels, count
fields, and route projection live in
`features/documents/config/document-distribution-lanes.ts`. A new lane is not
complete until both registries, the receipt constraint, mobile projection,
WhatsApp defaults, and compatibility tests are updated.

## Route hierarchy

```text
/documents/distribution
  /visa
    /{groupId}
  /flight-tickets
    /{groupId}/{international|domestic}/{onward|return}
```

The legacy group URL remains a group-scoped Visa/Flight Tickets chooser so old
bookmarks and notifications keep their group context. Route state selects one
immutable workspace lane; changing the lane remounts transient upload state.
Pending operations block navigation, and checked but uncommitted PDFs require
an explicit discard confirmation.

## Verification and upload flow

```text
browser selection
  -> bounded 16-file / 8 MiB verification chunks, one HTTP chunk at a time
  -> isolated, deployment-bounded PDF parsing and OCR
  -> strict structural Visa/flight classification
  -> deterministic, group-scoped passenger matching
  -> encrypted staging receipt bound to actor, group, lane, roster and chunk
  -> sequential, idempotent receipt finalization (no second PDF upload/parse)
  -> bounded server-side object copy and one database transaction
```

The 16-file cap halves request/process-start overhead for small-PDF batches
compared with the former 8-file cap. The independent 8 MiB byte cap,
single-request admission, two isolated parser workers, retry envelope, and
sequential commit order remain unchanged.

## Accuracy and safety invariants

- Filenames never determine document type.
- Unreadable, unrelated, payment, application, and unsupported PDFs fail
  closed.
- Automatic assignments require a confirmed passenger inside the authorized
  group; ambiguous matches are never persisted as automatic assignments.
- Shortened two-token airline names are evidence only in an explicit passenger
  manifest and only for a single `SURNAME, GIVEN` row with one unique owner.
- Verification receipts are fingerprinted and revalidated against current
  roster and linked-source state before persistence.
- Chunk tokens are immutable and idempotent; a replay with different bytes or
  scope is rejected.
- Existing documents, deliveries, audit rows, and storage objects are never
  removed by a taxonomy migration.

## Release order

Apply migration `0080_domestic_ticket_lanes` before serving frontend or backend
code that can submit Domestic chunks. Then deploy every backend consumer
(including workers), deploy the frontend, and verify Visa plus all four ticket
lanes. An application rollback should leave the additive migration in place.
The migration downgrade intentionally refuses to narrow the constraint while
Domestic receipt rows exist; it does not delete or relabel them.
