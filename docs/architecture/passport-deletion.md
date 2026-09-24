# Passport deletion

## Legal-hold feature retirement (2026-09-25)

Legal holds no longer block passport deletion, group deletion, manager-owned
data deletion, platform/agency purges, public draft discard, or scheduled passport
cleanup. Existing saved hold flags have no effect. The frontend hold controls and
the API for placing/releasing holds have been removed; an old client attempting
`PUT /api/v1/admin/groups/{id}/passport-retention` receives HTTP 405.

Normal retention dates still apply to scheduled cleanup. A previously held group
whose purge date has passed is eligible on the next lifecycle run. Manual group
deletion still requires an archived group and the selected record-retention
choice. Role/tenant authorization, recent MFA, CSRF, row locks, audit events,
roster-decision checks, private-delivery checks, and durable object cleanup remain.

Historical hold columns and audit records are preserved for schema compatibility;
they are no longer exposed as active application settings. No database migration
or environment-variable change is required. Deploy the backend and worker code
together with the frontend; old workers would otherwise retain the previous
scheduled-cleanup behavior. Rolling back to old code also restores its hold gates.

The retained read-only `GET /api/v1/admin/groups/{id}/passport-retention` endpoint
returns the group ID, purge date and retention days, using existing admin and
tenant authorization. It does not expose or change historical hold metadata.

The archived-group deletion dialog displays the server's error when another
condition blocks deletion. It keeps the selected request pending during identity
confirmation, prevents duplicate actions, and permits a deliberate retry after
failure. It does not silently release controls or retry a business conflict.

Regression coverage includes persisted legacy flags on deletion/cleanup paths,
denial for unauthorized roles or tenants, removal of the hold-mutation endpoint,
and a browser journey through MFA, a displayed conflict, and manual retry.
