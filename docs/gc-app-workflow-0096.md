# GC App workflow and submitted-phone login — release 0096

## Staff workflow

Open **GC App → App Controls**. This is now the default GC App page.

1. **Add group to GC App:** choose a passport group and its company/client. The passport collection link can be open or closed. Adding a new group enables the app immediately with the existing default roles; the dialog explains this before saving.
2. **Open trip → Overview:** check app availability and collection status separately. Configured paused trips remain in the list.
3. **Access & features:** choose permitted roles, optional My Photos visibility, and the access start/expiry. Date inputs use the operator's local timezone and send a timezone-qualified instant to the server.
4. **Documents:** upload a draft, preview it, then publish it. A replacement draft leaves the currently published version available until the replacement is published.
5. **Announcements:** save a draft, publish now, or set a future visibility start. Editing and publishing a replacement happens in one server transaction. Phone notification delivery has its own status view.
6. **History:** inspect the paged audit history when needed.

**Pause app access** preserves stored role settings, dates, and content. Enabling/restoring access respects those settings; it does not automatically sign a user back in. Changing access policy can end existing sessions. The separate emergency revocation action instructs devices to clear that trip's scoped offline data.

Closing a collection link stops new collection submissions. It does not, by itself, turn off GC App access. Archived/deleted passport groups remain unavailable to mobile users.

## Passenger login

Passenger OTP eligibility uses the current WhatsApp contact on a completed public collection submission. It does not use broadcast membership, imported roster phone fields, or family-head fallback. The same canonical phone normalization is used for login and the stored submission.

- A submitted **Needs review** record may establish login eligibility; passport approval and document-release rules remain separate.
- An unfinished upload or a record known to come only from Excel does not establish eligibility.
- New public submissions receive a reserved server-owned provenance marker. Excel imports cannot set it. A legacy genuine submission keeps its contact authority when an import updates other fields without changing its canonical contact.
- Existing session grants and notification targets are rechecked against the current submission. A stale phone binding cannot continue through refresh, switching trips, or using another already-granted trip.
- Shared-number identity selection and secondary proof remain in place.

The phone-entry response remains neutral. After a correct OTP proves ownership, the updated app can explain:

| Access state | App heading |
|---|---|
| Not configured, disabled, passenger role disabled, or revoked | Your trip is not active in GC App yet. |
| Access start is in the future | Your trip access starts later. |
| Access period ended | Your trip access has ended. |

These responses contain no access token or trip names. Existing installed apps retain the active-login contract; the new explanatory screens require app **1.0.5 / Android version code 6**.

## Reliability and operating limits

- Group availability is calculated on the server. Search filters apply before database count/pagination. Paused groups can be restored without re-adding them and overwriting their configuration.
- Revision checks reject a competing operator's stale save. The dashboard preserves unsaved date/editor values during unrelated refreshes and failed requests.
- Announcement save-and-publish rolls back completely if publication/audit/notification-enqueue persistence fails. Publishing a replacement retires the old version before promotion within the same transaction.
- Announcement and history queries are paged; inactive tabs do not fetch those resources. Access summaries refresh every 30 seconds while visible.
- Login phone discovery has a PostgreSQL expression index. Candidate discovery is bounded to 100 records per normalized phone; session grants remain bounded to 50. An overflow fails closed and records a bounded diagnostic event instead of authorizing a partial identity set.
- The existing common-document admin list/reorder contract remains capped at 200 draft/published versions per trip. Larger document libraries need a separate paging and global-ordering change. This release does not claim unlimited per-trip content.
- Publishing while a trip has no eligible recipients does not promise a future push when access is later enabled. Check notification status and publish the intended announcement when its audience is ready.
- Provider acceptance and a notification visibly appearing on a phone are different evidence. The owner performs the remaining physical-device test.

## Migration and release

`0096_mobile_phone_lookup` adds `ix_passport_submissions_mobile_phone_lookup` to the existing passport table. It does not rewrite phone values or remove records. Normal index creation is performed during the brief controlled release window.

Use `scripts/release_gc_group_access.py prepare --revision <exact-main-commit>` followed by `activate --revision <same-commit> --traffic-paused` only after ingress and queues are drained. It prepares backend/frontend/worker images together, requires a validated database backup, and retains recovery images and one-off containers. A retry after migration requires the same commit's original 0095 backup evidence.

Verify the exact deployed revision, schema 0096, seven workers and Beat, readiness, frontend, unchanged infrastructure volumes, and preserved table counts. Keep the previous private APK and the original database archive. Do not downgrade to application code with the old content-withdrawal trip-purge behavior.

## Verification coverage

Regression coverage includes public-submit versus import provenance, closed-link/app independence, all availability states and pagination, stale nonselected session grants, notification target changes, single-transaction publication failure, deterministic replacement UUID ordering, and simultaneous operator saves on real PostgreSQL. The PostgreSQL planner test applies the actual migration to 20,000 synthetic records and checks both custom and generic query plans.

Browser tests use the real dashboard with isolated synthetic API responses. Android tests and signed artifact inspection are separate from a live phone/WhatsApp notification journey. Production activation and physical-device results belong in the release handoff rather than being inferred from these source tests.
