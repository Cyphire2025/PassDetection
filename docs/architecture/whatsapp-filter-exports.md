# WhatsApp broadcast filter exports

Each broadcast's Delivery numbers and Travellers lists expose **Export Excel**.
The export uses the currently selected filter and search. Delivery numbers also
uses the selected message type. **All** exports all matching rows in that list;
checkbox selection and pagination do not narrow the export.

## Selection and authorization

The client sends a snapshot of the matching row identifiers to
`POST /api/v1/whatsapp/groups/{group_id}/export`. The request identifies its `view`,
tagged `items`, and optional `filter_label` and `message_type` context. Identifiers
are validated on the server against the authorized broadcast. They are not
permission grants, and labels do not drive database access.

Delivery rows identify recipients, rejected contacts, replaced recipients, or
unidentified submissions. Traveller rows identify the source submission and its
source group. Every requested identifier must still be eligible for the respective
list; stale or unauthorized identifiers cause a failure instead of an incomplete
successful download.

Source-group details are separately constrained by agency, group visibility,
export permissions, and the current operational submission rules. A visible
broadcast does not grant access to every passport group linked to it. Shared
phones expand to their exact linked travellers; ambiguous matching candidates
must never be treated as established passenger identities.
For the Replaced contacts filter, explicitly recorded displaced submissions may
provide the original traveller's details. The replacement person's details are
not substituted for the original traveller.

## Workbook data

Source-contact snapshots contain only a small contact summary. Where an exact
source association or an established group match exists, export data comes from
the authoritative underlying submissions and includes the main group field
values, additional saved import/staff details, custom answers, and delivery
context. Broadcast-imported fields remain available for manually created lists;
unmatched or inaccessible source details are not guessed or disclosed.
System tokens, storage credentials, and internal processing payloads are not
export fields.

The main passport export's reviewed-over-extracted field precedence is retained.
Supplemental fields are labeled so an original imported value cannot silently
overwrite a reviewed passport value. Each shared-number traveller retains an
individual row. Missing or invalid numbers remain exportable from the Traveller
list. Delivery status may change after the list was loaded; the exported selection
uses the requested IDs and the data values read for that export.

Identifiers and telephone values are written as text. Untrusted cell values are
not evaluated as formulas. Workbook generation must remain bounded and any size
limit must fail clearly instead of silently dropping rows or fields.
The current limits are 20,000 requested/expanded rows, 1,024 columns, two million
cells, 32 million escaped text characters, and 64 MiB of UTF-8 text. Individual
cells must also fit Excel's 32,767-character limit. Database tuple lookups are
batched, and worksheet rows use the write-only Excel writer with shared styles.

The download reuses the authenticated streaming helper, with cancellation on
dialog closure or session changes. Export does not queue messages, change contact
matching, update delivery status, or advance normal passport-export baselines.

No schema migration is required. This change was reviewed in source only, following
the user's instruction to skip tests, builds, and runtime checks.
