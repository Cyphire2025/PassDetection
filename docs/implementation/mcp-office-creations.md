# Additive menu and hotel creation

This is a locally qualified Phase 7 increment. All phase gates remain open.
The typed tools are registered by `register_office_change_tools`; their actual
authority is the static `MCPToolPolicy` and transaction service, not SDK metadata.

| Tool | Shared behavior and retained state |
| --- | --- |
| `create_menu_category` | Explicit agency ID or explicit null platform library; normalized unique category name and website sort order. Creates one new category. |
| `create_menu_dish` | Exact category and current revision; locks parent, validates scoped unique name, adds active dish, advances parent revision. Existing dishes remain unchanged. |
| `create_meal_plan` | Explicit category IDs and exact revision map; website active-dish selection and balanced nonrepeating lunch/dinner generator. Saves a separate plan and snapshot entries; existing plans remain intact. |
| `create_rooming_hotel` | Explicit agency/group, shared group-view policy and current nondeleted group; website hotel/date schema. Adds a stay with no rooms, selections, allocations or physical events. |

`application/use_cases/menu/create_menu.py` and
`application/use_cases/rooming/create_hotel.py` contain the shared flush-only
creation logic. The website retains its request validation, policy, audit and
response behavior. A fixed menu support bundle supplies existing queries,
revision fences and generator rules; neither transport invokes a route handler.
No callback commits, accesses files or sends network requests.

The MCP transaction owns entity writes, business audit and durable idempotency
receipt together. Repeating the same actor/operation/key across connections
returns the original IDs. Changed input under the same key conflicts. Retry does
not overwrite later staff edits or rerandomize a plan. Receipts omit free-text
names/notes, credentials and upload tokens. Replay and operation inspection
recheck live actor, active agency, current entity existence/scope and hotel group
access. Moving/deleting an entity or deleting its group makes that receipt
unavailable through MCP.

Local evidence on 2026-09-29:

- `tests/integration/test_mcp_office_changes.py` plus existing
  `test_menu_meal_planner_api.py` and four rooming presentation suites: **65 pass**.
  Includes actual SDK dispatch through the shared invocation/commit/audit
  boundary, cross-connection retries, changed-input conflicts, rollback on audit
  failure, removed/moved entity checks, active agency checks, scoped platform
  menus, stale revisions, invalid/unsupported fields and retained plan entries.
- `tests/service_integration/test_mcp_office_postgresql.py`: **6 pass** on the
  isolated PostgreSQL 16.15 database at loopback. Six concurrent requests per
  tool create one entity and audit; two distinct dish requests sharing a parent
  revision have one winner; two intended plans preserve both four-entry plans.
- Six changed production sources pass mypy; eight scoped sources/tests pass Ruff.

This does not qualify production, real Codex or all menu/rooming operations.
Saved-plan regeneration still needs a retained-version adapter. Current rooming
auto-allocation and passenger selection clear plans and therefore need an
additive/version-retaining design. Five hidden manual-room compatibility routes
already return HTTP410 and remain retired. Their retirement does not exclude
the active allocation workflow from required future implementation.
