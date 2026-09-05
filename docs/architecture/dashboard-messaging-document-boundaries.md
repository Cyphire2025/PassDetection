# Dashboard messaging and document boundaries

The public document-distribution and WhatsApp API paths, endpoint names,
parameters, response models, role guards, CSRF guards and registration order
remain unchanged. The original route modules compose focused routers and retain
explicit compatibility exports. New code should import the owning module.

## Document distribution

The `document_distribution_*` modules separate group reads, authorization and
roster locking, matching inputs, response rendering, verification, upload,
upload abort, reupload, assignment mutations, save, delivery preview and send.
Shared ingestion, verification receipts and storage transfer services remain
the canonical persistence paths.

- Authorization and operational roster selection happen before matching.
- Operational counts, passenger searches and delivery previews exclude active
  rejected/replaced roster entries. Historical records remain available in
  their existing history paths.
- Verification receipts, immutable chunk fingerprints, assignment capacity,
  tenant scope checks and post-processing roster revalidation remain in place.
- Database mutations and object transfer phases retain their existing explicit
  commit and cleanup boundaries. Retryable verification failures retain their
  staged objects for recovery.

## WhatsApp

The `whatsapp_*` routers separate signed webhooks, contact import, group reads
and mutations, recipient roster, rejected contact resolution, composer, recipient
mutations, resend, send and batch status. Parsing, composer snapshots and delivery
state policies remain shared support components.

Workers snapshot immutable log IDs and the rendered group name before iterating
over recipient transactions. Rollback may expire every ORM object in an async
session, including primary keys. Successfully claimed rows are explicitly
reloaded before use. A partial-batch retry preserves accepted deliveries,
suppresses uncertain deliveries and continues with still-queued recipients.
Commit acknowledgement recovery preserves a more advanced webhook status.

Publication runs in the bounded ASGI thread pool after durable intent commits.
A broker acknowledgement failure can mean that a task was already accepted.
Compensation therefore atomically fails only still-queued rows and releases only
their still-queued ledger claims. Processing and accepted deliveries are never
released or regressed by publication compensation.

## PDF processing

PDF safety inspection and isolated parser admission remain mandatory on the
production parsing path. Embedded text remains the first extraction path, and
existing successful OCR retains the block layout. Sparse layout OCR is attempted
only after empty block OCR, within the same deadline.

Native text reads are bounded before native allocation. Document, page,
text-page, bitmap and image resources close deterministically, including error
paths. Render scale enforces the pixel ceiling before rendering large pages.
Equivalent Unicode glyphs, ligatures and invisible PDF artifacts normalize
before detection; visually confusable identifier characters are not guessed.

Exact repeated classification inputs reuse work within one request. Filename,
expected document lane and content digest all participate in the key. Every
input position remains represented, and no document text cache survives the
request. Matching still requires the existing deterministic identity evidence
and retains conservative ambiguity outcomes.

## Verification boundary

The isolated regression suite covers API contracts, matching layouts,
verification staging, delivery behavior, a real async ORM partial retry,
publication compensation and event-loop responsiveness. It includes native
resource bounds and Unicode normalization regressions. Tests never send real
provider messages. They do not establish production provider behavior,
production throughput, physical-document OCR accuracy or PostgreSQL contention
under concurrent operators; those require separate retained runtime evidence.

Legacy route tests patch imported dependency consumers through the test-only
`tests/route_dependencies.py` helper. Production code uses static imports and
does not rebind module globals or install module proxies for mocking.
