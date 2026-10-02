# Direct MCP devices inventory checkpoint

Reviewed on 2026-10-02 against source commit
`db987053166b5f30bb413e27bf9f53e4885fd0a4`, using the original
`mcp-application-workflows/PassDetection` checkout as the unchanged baseline.
Discovery and validation used `scripts/mcp_inventory.py` without importing the
application or changing that checkout.

| Source and ledger state | Discovered surfaces | Ledger rows | Unclassified | Changed contracts | Total errors |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1,521 | 1,510 | 11 | 12 | 23 |
| Device candidate before ledger review | 1,524 | 1,510 | 14 | 12 | 26 |
| Device candidate after this review | 1,524 | 1,513 | 11 | 9 | 20 |

The device change adds exactly three discovered surfaces. They are classified
as `server_control`, with `exclusion_boundary: no_server_control`, null phase,
and `not_applicable` implementation status for MCP business-tool exposure:

- `frontend:frontend/features/mcp/api/mcp.api.ts:setConnectionAccess`
- `openapi:PATCH:/api/v1/admin/mcp/connections/{connection_id}/access`
- `route:backend/app/presentation/api/v1/routes/mcp_admin.py:set_connection_access:PATCH:/connections/{connection_id}/access`

These surfaces implement a superadmin browser control protected by recent MFA
and cookie CSRF. The endpoint changes an independently authorized connection's
access and must never appear as an MCP tool that can change its own authority.
Retained browser and backend evidence is in
`frontend/features/mcp/components/mcp-devices.test.tsx` and
`backend/tests/integration/test_mcp_device_access.py`.

Only the following three existing facade or registry fingerprints were updated
for the inspected device-access diff. Their classification and other review
metadata were preserved:

- `frontend_api:frontend/features/mcp/api/mcp.api.ts`
- `frontend_api:frontend/lib/api/endpoints.ts`
- `endpoint_registry:frontend/lib/api/endpoints.ts`

Those complete-file fingerprints were already stale at the baseline. Updating
them records the reviewed device-access addition; it does not reconcile the
previously unclassified operations in those files. No other existing ledger row
or unrelated business source was changed.

Validation asserted exact error-set equality: the remaining 20 errors are the
baseline's 23 errors minus the three reviewed facade or registry fingerprint
errors. All 11 preexisting unclassified surfaces and the other nine changed
contracts remain. There are no new device-access inventory errors after this
update. The full repository `mcp_inventory.py --check` still fails on those
preexisting gaps; this checkpoint does not claim a passing global gate, deployed
capability, or successful authentication in a real native client.
