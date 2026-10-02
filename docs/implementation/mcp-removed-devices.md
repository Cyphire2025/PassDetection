# Removing an obsolete MCP device from the dashboard

The Devices list omits a grant only when it is already revoked and its `revocation_reason` is exactly `administrator_removed`. This explicitly archived state preserves the grant, credentials, historical operations, artifacts and audit references. Credential validation continues to reject the revoked grant.

Other revoked connections remain visible as Disconnected. Active or disabled connections remain visible even if they accidentally carry the removal marker. Filtering happens before pagination so hidden entries do not occupy rows or create a false next page.

The initial maintenance action is authorized by the user's request to remove **Nipun’s Codex desktop** from the live main site. Its verified live ID is `27ab38f4-e13b-4289-bbe8-a1fd9658a97a`, and it was already revoked with `administrator_revoked`. It has historical operation and artifact references, so deleting its grant would damage provenance.

The live maintenance procedure must retain a private before snapshot, lock and recheck the exact ID/name/client/revoked state, change only its removal reason, and append `mcp.connection_removed` through `AuditLogRepository.record` in the same transaction. The maintenance audit actor is anonymous/system (`user_id=None`); an administrator session is not fabricated. Other grants, access permissions, credential rows and existing audit entries must remain unchanged.

This change requires no schema migration or frontend change. A narrow retained backend deployment can keep the current frontend, workers and infrastructure. Application revisions for those unchanged services remain their earlier deployed revision; the backend image and proxy cutover must be recorded separately.
