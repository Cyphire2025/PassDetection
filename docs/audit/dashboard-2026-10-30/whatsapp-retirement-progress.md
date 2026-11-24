# Current WhatsApp workspace checks and dead UI retirement

The branding/documents audit agent established a closed unreachable subtree of 31 runtime modules and retired their implementation-only tests. Its original hashes and caller graph are preserved in `documents-retired-files.json`; this integration does not remove or alter live backend endpoints, runtime hooks, routed workspace screens, role policies, or provider operations.

The old `whatsapp-source.contract-helper.mjs` combined unrelated retired screens into one string. Six source-contract suites and the WhatsApp part of the dashboard transformation suite were therefore checking an unreachable UI. The helper now reads one explicit owner at a time. Each check is bound to the actual routed broadcast index, composer, recipient exceptions, delivery history, or shared import owner. No unrelated sources are concatenated to satisfy an assertion.

The current workspace already has different presentation and history semantics from the deleted screens. The replacement checks cover its real behavior: one named historical recipient and original message log; retained resend request ID; dedicated document-update retry route; consent and archived states; approved current previews; welcome eligibility; server-confirmed audience intersection; selected support contact; bounded searchable pages; import headings and rejected rows; restored recipient resolution identity; and current broadcast/document/QR batch registration. Existing role-access and delivery eligibility tests remain in place. The old dead-screen-only mobile card, dialog stacking, text-label and toolbar assertions were retired with those implementations; they do not establish properties of the current workspace.

Added direct behavior tests of the existing live `useMessageComposer` hook and `historyApi`, with synthetic fixtures and mocked transport boundaries. They verify stale previews before debounce, blocked consent/archive/template/welcome/query states, ambiguous reminder groups, empty selection, rapid duplicate submission, exact recovery payload/snapshot after edits, explicit uncertain-intent recovery, original message-log/request identity, dedicated document retries, and encoded paginated history queries. Production runtime code was unchanged by this integration.

Inventory reconciliation retires only three identities belonging to the deleted `traveller-welcome.api.ts` facade. All remaining classifications, effects and runtime permissions are preserved. The manually reviewed attachment-filename fix receives a fingerprint-only update: RFC5987 `filename*` is decoded; ordinary `filename` stays literal before the existing safe-name sanitizer. The security agent confirmed its 15 focused download tests passed. `whatsapp-retirement-inventory.json` retains the full retired rows and before/after fingerprint evidence.

None of the 31 retired paths had an entry in the current frontend module budget, so no budget entry or ceiling was changed. All 124 live ratchets pass. The strict release policy retains its exact two reviewed baseline commits and all source/proof admission checks. Added an exact binding for the reviewed `nginx/conf.d/default.conf` native-transfer proxy location; all 19 candidate hashes and both baseline hash sets were independently checked against source/Git. The frontend budget hash remains `8596ea0b4e7af3c817c0ec58e5d319cf81c0ba0580a7c56016b6214bf3b9d418`.

Verification for this integration:

- Seven migrated Node suites: **44 passed**.
- Current composer/history API plus existing composer dispatch Vitest tests: **21 passed** across three files, from `frontend/` with its real Vitest configuration.
- ESLint for all ten changed/new contract and behavior-test files: **passed**.
- Release upgrade/schema unit tests: **28 passed**.
- Strict release builder and inventory tests: **25 passed, 9 subtests passed**.
- MCP source inventory: **1,950 surfaces, classification check passed**.
- Frontend size/complexity ratchets: **124 live modules passed**.
- Exact release binding audit: **19 current AFTER bindings and both source baseline sets passed**.

An initial Vitest invocation from the repository root lacked the frontend alias/configuration and collected no tests; it was corrected to the documented frontend working directory. Initial source-contract migration had two incorrect property assertions; they were corrected against the actual source and the full seven-suite run passed. No real provider calls were made. Browser evidence is owned by the branding agent (current WhatsApp nine-case isolated browser suite passed); the root agent runs final combined type/lint/build/Node checks. Real Docker Nginx/PostgreSQL release qualification remains unavailable locally; source/unit evidence does not claim a deploy-qualified VPS release.

`whatsapp-retirement-reviewed-files.json` records current hashes and honest focused/full review scope. `final-retirement-release-bindings.json` captures exact release binding evidence. No claim is made that this targeted integration completes the repository-wide audit.
