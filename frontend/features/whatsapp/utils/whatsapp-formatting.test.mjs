import assert from "node:assert/strict";
import test from "node:test";
import {
  parseWhatsAppBoldSegments,
  toggleWhatsAppBold,
} from "./whatsapp-formatting.ts";

test("wraps selected WhatsApp text in bold markers", () => {
  assert.deepEqual(toggleWhatsAppBold("Hello world", 6, 11), {
    value: "Hello *world*",
    selectionStart: 7,
    selectionEnd: 12,
  });
});

test("a second bold click removes markers around selected text", () => {
  assert.deepEqual(toggleWhatsAppBold("Hello *world*", 7, 12), {
    value: "Hello world",
    selectionStart: 6,
    selectionEnd: 11,
  });
});

test("an empty selection starts and stops a bold typing region", () => {
  const started = toggleWhatsAppBold("Hello ", 6, 6);
  assert.deepEqual(started, {
    value: "Hello **",
    selectionStart: 7,
    selectionEnd: 7,
  });

  const typed = "Hello *world*";
  assert.deepEqual(toggleWhatsAppBold(typed, 12, 12), {
    value: typed,
    selectionStart: 13,
    selectionEnd: 13,
  });
});

test("parses WhatsApp bold markers into safe preview segments", () => {
  assert.deepEqual(parseWhatsAppBoldSegments("Hello *bold* text"), [
    { text: "Hello ", bold: false },
    { text: "bold", bold: true },
    { text: " text", bold: false },
  ]);
});
