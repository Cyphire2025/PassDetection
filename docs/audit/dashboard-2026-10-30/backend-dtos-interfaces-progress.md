# Retained DTO and application interface review

The 16 retained inventory targets were fully physically read (931 lines). The
source-bound ledger records 11 additional complete supporting reads and 14
bounded supporting reads separately. Metadata, import searches and an AST
reference graph do not count as complete physical source reads.

- [Current review ledger](backend-dtos-interfaces-reviewed-files.json)
- [Source fence and explicit deferred interfaces](backend-dtos-interfaces-source-fence.json)
- [Read-only conclusions and limits](backend-dtos-interfaces-verification.json)

Authentication explicitly projects safe session/user JSON and establishes the
internal token values through the existing cookies. The passport response model
omits the DTO's internal cleanup/promoted-storage lists and replay marker.
Notification history explicitly projects aggregate recipient/device counts,
without push registration tokens. The inspected downstream WhatsApp sanitizer
already bounds imported field count, value length and UTF-8 bytes.

MRZ parsing and the passport field validator are active dependencies of AI
source acceptance/verification. Those contracts were preserved. This review
does not equate returned AI MRZ validation with the removed OCR extraction path.

The dedicated Operations Inbox `email_analysis` and `email_provider` interfaces
remain deferred by the user's exact scope policy. The outgoing identity
recovery notification interface is retained. No provider, PostgreSQL or native
device calls were made. No runtime/test/configuration changes or suites were
needed for the read-only DTO/interface cohort.

The separate disconnected WhatsApp foundation candidate has an exact
[closure proposal](whatsapp-foundation-closure-proposal.json) and
[retirement/obligation plan](whatsapp-foundation-retirement-plan.json). The graph
covers 1,646 application Python modules with direct/relative imports and exact
module-valued literals used by fixed loaders/registries/Celery; all five proposed
modules are outside the API/worker entrypoint closure and have no incoming
application reference outside that closed group. Whole maintained literal and
symbol searches find the historical architecture note and one prototype-only
test as the remaining external consumers. Actual fixed MCP loader, package,
deployment/worker entrypoints and current template settings were inspected.
This is supporting reachability evidence, not a claim that static Python graphs
prove arbitrary reflective execution impossible.

The focused existing message-template baseline passed all nine cases
(`.tmp/whatsapp-foundation/baseline-tests.txt`). The plan preserves the eight
current message/header/body/default tests exactly and carries the prototype
case's four template-name/language assertions to the actual current resolver.
The live provider, API schemas, settings, worker, billing and source-sync paths
remain outside the proposed five-file retirement. No retirement mutation has
been applied at this stage; exact paths were sent to the parent for shared
WhatsApp ownership coordination.

The parent subsequently coordinated and authorized those exact five paths.
Their 8,017 original bytes were moved into the ignored local archive with each
source/destination absolute path and SHA-256 verified before and after the move.
The [retirement manifest](whatsapp-foundation-retirement-manifest.json) lists
only those five original paths; the [current proof](whatsapp-foundation-retirement-proof.json)
shows zero maintained consumers, 139 retained WhatsApp source hashes unchanged,
the eight other test ASTs unchanged and the same four expected values executing
the live resolver. The [qualification](whatsapp-foundation-retirement-verification.json)
records 9/9 affected tests passing, Ruff check passing and final formatter check
passing. The formatter corrected pre-existing wrapping/EOL only, with the entire
test module AST identical before/after formatting. No broad suite/build/browser
or provider operation was run. The exact MCP discoverer emitted no identities
for these five primitives, so this cleanup requires no MCP identity retirement.
Original read-only proposal records remain historical; the separate
[follow-up reconciliation](backend-dtos-interfaces-followup-reconciliation.json)
closes DT01 only through this retirement qualification.
