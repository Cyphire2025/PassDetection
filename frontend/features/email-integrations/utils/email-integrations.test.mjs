import assert from "node:assert/strict";
import test from "node:test";
import {
  cleanEmailOAuthCallbackUrl,
  formatEmailLabel,
  isEmailProcessingActive,
  isSafeOAuthAuthorizationUrl,
  normalizeEmailCollection,
  readEmailOAuthCallback,
} from "./email-integrations.ts";

test("normalizes both direct arrays and collection envelopes", () => {
  const items = [{ id: "one" }, { id: "two" }];
  assert.deepEqual(normalizeEmailCollection(items), items);
  assert.deepEqual(normalizeEmailCollection({ items }), items);
});

test("OAuth redirect accepts HTTPS URLs and rejects unsafe or malformed URLs", () => {
  assert.equal(
    isSafeOAuthAuthorizationUrl(
      "https://accounts.google.com/o/oauth2/v2/auth?state=opaque",
    ),
    true,
  );
  assert.equal(isSafeOAuthAuthorizationUrl("http://accounts.google.com/auth"), false);
  assert.equal(
    isSafeOAuthAuthorizationUrl(
      "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    ),
    true,
  );
  assert.equal(isSafeOAuthAuthorizationUrl("https://attacker.example/auth"), false);
  assert.equal(isSafeOAuthAuthorizationUrl("javascript:alert(1)"), false);
  assert.equal(isSafeOAuthAuthorizationUrl("not a url"), false);
});

test("OAuth callback notices come only from fixed status values", () => {
  assert.deepEqual(readEmailOAuthCallback("?email_oauth=connected"), {
    tone: "success",
    message:
      "Gmail was connected successfully. Inbox monitoring will begin shortly.",
  });
  assert.deepEqual(
    readEmailOAuthCallback("?email_oauth=connected&email_provider=outlook"),
    {
      tone: "success",
      message:
        "Microsoft Outlook was connected successfully. Inbox monitoring will begin shortly.",
    },
  );
  assert.equal(
    readEmailOAuthCallback("?email_oauth=%3Cscript%3Ealert(1)%3C%2Fscript%3E"),
    null,
  );
  assert.equal(readEmailOAuthCallback("?message=provider-controlled"), null);
});

test("OAuth callback cleanup removes sensitive and feature-owned parameters", () => {
  const cleaned = cleanEmailOAuthCallbackUrl(
    new URL(
      "https://travel.example/email-integrations?email_oauth=connected&email_provider=outlook&code=secret&state=opaque&view=all#connections",
    ),
  );
  assert.equal(cleaned, "/email-integrations?view=all#connections");
});

test("human-readable labels and active processing states remain deterministic", () => {
  assert.equal(formatEmailLabel("needs_review"), "Needs Review");
  assert.equal(formatEmailLabel(null), "Not available");
  assert.equal(isEmailProcessingActive("PROCESSING"), true);
  assert.equal(isEmailProcessingActive("completed"), false);
});
