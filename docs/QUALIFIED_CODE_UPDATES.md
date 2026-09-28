# Qualified updates on the current database schema

The main CI workflow qualifies exact backend/frontend images, publishes their
signed inventory and provenance, and then runs the protected `production-vps`
deployment job. Both publication and deployment retain the configured owner
approval gate. The VPS independently checks the successful qualification and
publication jobs and verifies image signatures, source revision and the current
dependency policy. A failed or superseded CI revision cannot activate.

This path is for the existing KVM4 deployment after schema
`0111_roster_revision` and the SeaweedFS migration are complete. The historical
`release_current.py` migration procedure is not the code-update entrypoint.

## Deployment configuration

The `production-vps` environment admits only `main` and contains:

- Secret `VPS_DEPLOY_KEY`: a dedicated deployment key, separate from temporary
  operator access.
- Secret `VPS_KNOWN_HOSTS`: the independently verified SSH host key.
- Variable `VPS_HOST`: the production server address.

Install the reviewed `scripts/release_ci_dispatch.py` outside the repository as
`/opt/globalconnect-release-tools/release_ci_dispatch.py`, owned by root and
mode `0700`. Bind the dedicated public key using OpenSSH `restrict` and the
forced command `python3 /opt/globalconnect-release-tools/release_ci_dispatch.py`.
The only accepted SSH request is `deploy-qualified:<40-character commit SHA>`.
The key cannot open a shell or request arbitrary commands or forwarding.

The dispatcher starts a retained systemd service with the root account's
existing GitHub/registry authentication directories. The service survives an
Actions/SSH disconnect. A server-side lock serializes the complete deployment,
including the final source checkout update. Logs remain private under
`/opt/globalconnect-release-tools/deployment-logs`; CI receives only the outcome.
Do not put production credentials in workflow YAML, logs or release assets.

## Release and recovery contract

`scripts/release_code_update.py` runs from a separate checkout of the qualified
commit and receives the existing production root. It discovers the active
Compose files from running container labels and preserves the storage, resource
and image overlays. It refuses schema or incompatible configuration/persistence
changes. It retains the source checkout until activation succeeds.

Before mutation, it verifies the live service identities and resource envelope,
retains previous immutable images, and creates a protected PostgreSQL custom
archive with checksum and full archive decode verification. This is backup
integrity evidence, not a production restore rehearsal.

The full production stack cannot be duplicated within the KVM4 budget.
Background consumers therefore stop accepting work and drain before a second
full-size API/frontend pair is admitted. Existing web services remain available
during candidate startup. Queued work is retained. The candidate must pass
revision, core capability, login and asset probes before Nginx can route traffic
to it. The previous images remain available for a same-schema recovery.

The helper never migrates or restores the database, replaces persistent
services, copies object storage, purges queues, sends test WhatsApp messages, or
deletes production volumes, object versions, release receipts or backups.
Protected state and backup files remain under the production root's
`tmp/code-updates` directory. Inspect the exact retained phase before recovery;
do not rerun historical migration scripts against this deployment.

This is a bounded single-host transition, not host high availability or a
guarantee that every existing long-lived client connection survives. If the
required capacity, compatibility, drain or readiness checks cannot be proved,
retain a verified serving release and investigate the recorded blocker. Do not
remove checks or take down the live release to force an activation.
