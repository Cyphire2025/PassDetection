# Storage replacement and preservation evidence

This is candidate/local qualification evidence, not a claim that the VPS has been
migrated. The original MinIO data volume must remain retained after cutover.

The reviewed maintained provider is SeaweedFS 4.47, pinned to manifest digest
`sha256:ce9e796f1fe6f06968f4c04bdaf8f678dad9c8acdfef3d244133d71bfa6bf882`.
Upstream [release notes](https://github.com/seaweedfs/seaweedfs/releases/tag/4.47)
and the [S3 API documentation](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API)
were checked on 26 September 2026. Maintenance status does not establish freedom
from vulnerabilities.

Actual adapter qualification uses the unchanged application
`MinioStorageRepository`: upload, full download, content type/checksum metadata,
range download, bounded streaming, full-body hashing, server-side copy, bounded
listing, signed URL, ordinary deletion, and historical-version retrieval pass.
Anonymous access, a second bucket, bucket creation, versioning suspension and
permanent object-version deletion by the application identity are denied.

Two deployment shapes were exercised. The split provider isolates master,
volume and filer on a storage-only network. The production override instead
binds those six HTTP/gRPC ports to container loopback, with only authenticated
S3 listening on the application network. TCP connection attempts to all six
internal ports from another application-network container fail. The actual
production override runs as UID/GID 1000 with all Linux capabilities dropped.

The production override was rendered with synthetic settings and started under
project `passdetection-production-storage-qualification`. The staging process
wrote versioned synthetic objects. After staging stopped, the stable `minio`
service opened the same new volume as a fresh process. Its health check passed
and an authenticated read returned the previously written bytes at `minio:9000`.
No original MinIO volume was mounted into SeaweedFS.

`scripts/qa/qualify_storage_migration.py` exercised real MinIO-to-SeaweedFS copy:

- Null versions, retained historical versions, current versions, delete markers,
  empty objects, Unicode keys, metadata and tags are preserved semantically.
  Provider-specific version IDs/timestamps change; the private journal maps IDs.
- 1,001 versions of one key cross pagination boundaries, including version-ID
  markers. Every copied body is independently read back and SHA-256 checked.
- A completed copy can be verified again without duplicating destination data.
- Source changes, target metadata/tag tampering, unexpected/missing versions,
  and changes during copy/final verification prevent success.
- A second process using a different journal in the same protected evidence
  directory cannot acquire the destination's migration lock.
- A real successful PUT followed by a simulated lost response leaves both the
  original and the copied orphan intact. Retry fails closed: it does not delete
  or overwrite that uncertain version to make the test pass.

That last case is deliberately **not automatic crash recovery**. With legacy
storage still active, the next release preparation allocates a fresh isolated
destination and evidence directory. Both the authoritative old volume and the
earlier partial destination remain retained. An operator may instead reconcile
the partial target after an independent review.

The copy helper rejects existing object-lock, default encryption, lifecycle,
bucket-policy, CORS and custom ACL configurations it cannot preserve. A real
MinIO owner-only compatibility ACL was checked and accepted. The release also
requires that the old provider contain exactly the configured application
bucket, so replacing its endpoint cannot silently strand another bucket. Such
additional buckets or protections require a separately reviewed migration.
Destination bucket creation occurs under the migration lock only after source,
journal-identity and disk-capacity checks. The process is a single-host,
maintenance-window migration: all configured application writers must be stopped
through snapshot verification and activation. No zero-downtime claim is made.

The repeatable CI command is `python scripts/qa/run_storage_migration_qualification.py`
after the qualification backend image is built. It uses two separate SeaweedFS
4.47 instances and explicitly records the source provider; it does not claim to
repeat the legacy MinIO compatibility check. Its full 1,001-version and failure
matrix passed locally. The old archived MinIO image was available in the local
Docker cache for the distinct migration proof, but current unauthenticated pulls
from its registries were denied. The CI protocol regression avoids depending on
that inaccessible legacy registry. Both synthetic source and destination
containers are isolated from the application network and removed after the run.

Local versioning is not an off-host backup. Production off-host recovery, PITR,
RPO/RTO and actual alert delivery remain separate, unresolved operational gates.
