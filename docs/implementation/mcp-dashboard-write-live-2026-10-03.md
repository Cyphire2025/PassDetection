# Live MCP dashboard write release — 3 October 2026

The native MCP read/write release is live at [MCP administration](https://tech.gctravels.com/admin/mcp), using the existing [Streamable HTTP endpoint](https://tech.gctravels.com/mcp). Independent verification completed successfully at **2026-10-03 01:28:10 UTC / 06:58:10 IST**. The application revision is **`4fa22b13286eae56871a34959bb77cdb333e1374`** and the database schema is **`0128_mcp_document_delivery`**. This checkpoint is a later documentation change; it does not change the deployed application revision.

See [the implementation contract](mcp-dashboard-write.md) for the exact workflows, authority checks, file transport and transaction boundaries. The Administration label is **MCP**; its pages are Devices, Requests, Settings and Connection setup. Settings and each device's Manage view independently control Read and Write. The live code includes the requested group, Excel, broadcast, rooming, menu, document, workforce, Tour Ops and GC App adapters, plus the existing five export families. Tool availability still depends on current policy and the original connection's approved scopes.

## Activating approved access

1. Open **MCP → Settings** in a Superadmin session. Under **Write settings**, enable **Allow write access**, select the intended sections and choose **Save permissions**. Keep the desired Read sections enabled independently.
2. Open **Devices → Manage** for the intended connection. Enable **Allow write access**, review its permitted sections and choose **Save access**. The connection must also be enabled and unexpired.
3. A connection originally approved for read alone cannot gain additional OAuth scopes through a settings switch. Start a new Authenticate request in the client and approve the requested actions under **Requests**, then review its device permissions. A client that requests only read scopes remains read-only.
4. For QR and attendance lookups, enable the relevant Tour Ops/GC App Read sections globally and on the connection. Existing canonical QR images and recorded attendance are returned; QR tokens are not regenerated for a lookup.

The existing recent-MFA requirement applies to Superadmin policy changes. Global Write and existing device Write were left **disabled by default**. All four existing grants retain their original scopes, read policy and enabled/revoked state. The release did not approve a device, expand an old grant or enable a business section on the administrator's behalf.

Outgoing messages, reminders, app notifications and document delivery require **prepare → exact preview → fresh final approval in the chat → confirm → worker authority check → submission**. Group creation, contact import, PDF ingestion and assignment save do not themselves send anything. If recipients, content or source revisions change, the old preview cannot authorize the changed action. The client must obtain and convey the user's final approval; the tool confirmation field is a contract, not cryptographic evidence of a human gesture.

## Observed live state

The retained successful proof is `outputs/mcp-dashboard-write-entrypoint-features-live-verification-3db410666c1c49c7abd23cd4b6a57a51.json`, SHA-256 **`3154e1c038faee3a2b570fe3aaf039e90a5bd2dea029e2854a12352af49c1e85`**. It records these observations:

| Check | Verified result |
| --- | --- |
| Running services | 20 running; all 18 configured health checks healthy. |
| Release consistency | 12 new application services, including backend/frontend/proxy and eight workers plus beat; eight infrastructure services preserved. 1,136 source files checked in each of backend, workers and beat, ten containers total. |
| Schema and saved authority | Schema 0128, preserved existing read policy and four grants, and denied Write defaults. The database policy probe used a read-only transaction. |
| SDK registration | 119 registered tools; 44 exposed under the stored policy. Eight synthetic policy cases passed in memory, without changing production policy or invoking business tools. |
| Frontend | Six compiled MCP routes and three current route-reachable feature assets verified against exact public response bytes. Read/Write settings, device permissions, Delete and native file save/hash features were present. |
| Public transport | Health/discovery checks passed; unauthenticated MCP returned 401. OAuth advertised only `mcp:read`, `mcp:change`, `mcp:upload`, `mcp:export` and `mcp:communicate`. Waiting and file-handoff pages had effective `no-referrer` policy. |
| Migration preservation | All 141 historical tables covered by the migration proof preserved. Additive migration helper image, command, environment and proof bound. New tables initially empty and Write defaults denied. No automatic downgrade. |
| Backup | 15,090,969-byte backup, SHA-256 `501e149f7de8b6c1b12933c26321ec2f6f5c22847f56a0fbe6296a49676bafa4`; complete archive decoding verified and database/writer-fence/source-contract bindings checked. This was not a restore rehearsal. |
| Retention | All baseline and intermediate resources retained: 440 containers and 207 images, including 12 stopped original and 12 stopped recovery application containers. Existing configuration and resource limits preserved. |
| Final runtime checks | No new application restart/OOM; no infrastructure restart/OOM delta. Runtime and memory checks repeated after public HTTP verification. |

The verifier made no remote mutation, production grant, authorization request, file credential request or business tool invocation. Production passenger/group/account records, uploads and outgoing messages were not created as test data. Live checks establish deployment, source, policy, migration, transport and runtime correctness; local qualification supplies the business workflow test evidence.

## Qualification and immutable lineage

The consolidated application qualification is `outputs/dashboard-write-consolidated-qualification-4fa22b1-20261003T004809Z.json`, SHA-256 **`5199e48ab57d979c647a0cef26aed719617bc314a9fef38bae483c020aee63fd`**. It binds all 4,241 committed source files to the deployed archive. The retained qualification evidence includes:

- The original 1,425-case MCP regression run had 1,412 passing cases and 13 failures from obsolete read-only fixtures/expectations. The corrected affected file then passed all 49 cases. An explicit overlay using exact testcase identities yields **1,425 passing case outcomes**, with no unresolved failures, errors or skips. This is **not** an uninterrupted 1,425-pass run.
- Separate qualification passed 94 backend foundation/native/schema cases, including actual PostgreSQL migration preservation and concurrency checks.
- Frontend qualification passed 191 unit cases, 23 administration browser journeys and eight file-transfer browser journeys, plus TypeScript, scoped lint and an isolated production build.
- Document qualification passed 93 combined regressions, 33 final focused cases including the native SDK, and a separate PostgreSQL contention case. These overlap other suites and are not summed into a larger claimed total.
- The final operator amendment passed 99 offline cases, consisting of 43 amendment cases plus 56 retained parent cases, independently run and reviewed. The final live verifier passed 150 offline cases and its scoped Ruff check before the successful live invocation.

The immutable deployment and verifier artifacts remain in ignored `outputs/` and the retained server release directory; preserve them when maintaining this worktree.

| Artifact | SHA-256 |
| --- | --- |
| Frozen original operator, `forward-mcp-dashboard-write-v1.py` | `44e7285202eeecebf6de2a4760d823a99142b71a201cf31a51bc67a38ffd79f0` |
| Reviewed additive operator wrapper, `forward-mcp-dashboard-write-entrypoint-amendment-v1.py` | `35193ceebee676b326ed62a5e20fd93bfc751f0ab8b46e600a25656a834f91ad` |
| Final independent verifier, `verify_mcp_dashboard_write_live_entrypoint_features_v1.py` | `dfabcf78421a9dd9c6fc34c7a55d2e6931d6aa01340afea2e3df6395ddf34663` |
| Committed source manifest | `eecdace11a64815df76837cb8186908458aa8b4e6d037c53d15fdc97ac60324f` |

The operator wrapper narrowly corrects the entrypoint guard to require the exact canonical clone payload, including the retained frontend/proxy entrypoints. It preserves the frozen operator, original baseline, approval, image/environment/resource/network/proxy checks and existing recovery clones. No rebaseline, rebuild, cleanup or downgrade was introduced. Its successful completion is linked to the original completion journal.

An earlier retained verifier failed because its feature scanner counted generic SHA-256 text in unrelated retained chunks. The final reviewed verifier selects feature assets through the current pages' client-reference manifests. It keeps the original count/size limits and checks exact served-byte hashes. The repair changed no application or deployed configuration; the old failure and verifier remain available for audit.

## Practical boundaries

- Native file handoff works without dashboard login on the requesting computer, but a remote server cannot read that computer's folder from a path alone. The AI/client must transfer the selected original files. Original filename/MIME/size/content hash and exact target are verified before review and application.
- Invited coordinator/staff/manager/client-manager accounts use the existing dashboard activation flow. MCP does not return passwords or activation credentials and does not automatically send invitations.
- Export limits remain **100 source rows and 1 MiB**. Document sends accept 1–100 explicitly selected saved documents; assignment inspection accepts at most 1,000 batches/documents. Send previews expire after 15 minutes. Larger jobs must be split explicitly.
- Disabling a device or relevant allowance blocks remaining unsent work through current worker authority checks. Unknown provider outcomes are retained rather than automatically retried; already-submitted provider actions cannot be recalled by a later toggle.
- Bounded queries, file parsing outside database transactions, revision checks, idempotent receipts and shared typed adapters provide the expansion foundation. This release makes no unlimited-volume, arbitrary-domain or fixed-latency guarantee.
