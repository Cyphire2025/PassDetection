# GC App Notifications — operator guide for release 0097

## Choose the right workspace

Open **GC App** and select the intended agency when an agency selector is available. Agency Admins, Agency Managers and Super Admins can manage notifications within their authorized agency.

| Task | Where to work | What the action does |
|---|---|---|
| Publish information inside one trip | **App Controls → open trip → Announcements** | Saves or publishes in-app content, with its visibility dates. Publishing does not send a phone alert. |
| Write and send a phone alert | **GC App → Notifications** | Saves a message, reviews the current audience, and sends only after explicit confirmation. |

For release 0097, this separation replaces the announcement-linked phone-delivery behavior described in the earlier 0096 guide. An announcement and a phone notification are independent messages. Editing either cannot change an alert already delivered to a phone. Notifications can also be read inside the app; this does not make them trip announcements.

## Write, review and send

1. Enter a **Notification title** of up to 100 characters and a **Notification message** of up to 240 characters. This text can appear on a lock screen; avoid private passenger or document details.
2. Choose the audience:
   - **All active GC App trips:** the server resolves the active trips and currently authorized app users in the selected agency when you review. New trips or access changes require a refreshed review.
   - **Specific groups:** select one or more active trips. Search and paging preserve selections; selected chips let you remove a trip. The server accepts at most 500 specifically selected groups. Collection links being open or closed does not determine app availability.
3. Use **Save draft** to keep the message for later, or **Review audience** to save and review it now. Neither action sends a notification. **Saved messages** includes drafts and previously sent messages; editing one preserves the earlier immutable send history.
4. On the review screen, check the exact text, included trips, eligible recipients, role counts, registered devices and recipients without an active device. The review lasts 10 minutes. Use **Refresh audience** after expiry or a relevant access change. A selected trip that becomes unavailable must be resolved before sending; it is not silently dropped.
5. Choose **Send notification** once ready. A recorded send appears in **Send history** and **Delivery summary**. Recording a send does not prove that a phone displayed it.

## Provider and device warnings

The review identifies whether Android and iOS delivery are enabled independently. An enabled provider setting does not verify credentials, network access or phone permissions.

If delivery is disabled or there are no eligible registered devices, the screen warns you. With eligible recipients, you can still explicitly record the notification; attempts remain subject to the 24-hour delivery window and current access checks. There is no promise that a later login, permission change or provider enablement will produce a visible alert. An audience with no eligible recipients cannot be sent.

## Read delivery status correctly

- **Queued / Waiting to retry:** work may still be attempted while the delivery window and recipient access remain valid.
- **Accepted notification / Provider accepted:** the provider accepted a handoff. These counts do not prove phone display.
- **Provider receipt received:** provider-reported evidence, also not proof that the person saw a banner.
- **Read in app:** the notification was marked read inside the app.
- **No active device registration:** recipients currently recorded with no eligible device registration.
- **Unknown outcome:** acceptance cannot be confirmed. These outcomes are not automatically resent because the phone may already have received the alert.

Recipient counts and device counts measure different things. Read counts and no-registration counts can overlap recipient states; do not add every displayed number together as a recipient total.

Each send has a **24-hour delivery window**. After it ends, remaining queued recipients and retries are labeled **Expired unsent** and will not be sent. Accepted and unknown evidence remains unchanged. Use **Refresh delivery status** to retrieve the latest recorded counts.

## Send again deliberately

In **Send history**, choose **Prepare resend**. This copies the earlier send's text and audience choice into the composer. Review the current audience and choose **Send again** to create a separate send. People who received the earlier alert can receive another one. Preparing the resend alone sends nothing.

## Recover a lost response

If the dashboard cannot confirm a send response, keep the same browser tab and use **Check recorded outcome**. This is a read-only lookup and sends nothing. The tab keeps only opaque recovery identifiers; it does not persist the message text or review token in session storage.

If no record is found, **Review and retry same request** loads the saved message and current audience. After explicit confirmation, it reuses the original send reference to prevent a second batch for that request. Refreshing the page does not automatically retry the send. Starting a separate notification remains blocked while the earlier result is uncertain.

If the server explicitly rejects the send because its audience, draft or eligible recipients changed before a batch was recorded, the editor unlocks and preserves the message for correction. If an uncertain send cannot be reviewed because trip access changed, keep its recovery reference, check the trip's access and recorded send history, and ask the platform administrator to investigate an unresolved outcome. Do not clear browser storage or start a new tab merely to bypass recovery; that can cause a duplicate alert.

## Verification boundary

Source checks and synthetic browser journeys cover audience selection, explicit send, deliberate resend, lost-response recovery and delivery-window wording. A notification appearing on a real Android or iOS phone requires a separate device/provider check. Deployment and physical-device results belong in the release handoff.
