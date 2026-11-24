import { readFileSync } from "node:fs";

// Keep each assertion bound to its actual owner; unrelated files must not
// accidentally satisfy a contract when responsibilities move.
export function readWhatsAppSource(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

function readWiredOwners(parentPath, owners) {
  const parent = readWhatsAppSource(parentPath);
  return [parent, ...owners.map(([name, path]) => {
    const isFunction = name[0] === name[0].toLowerCase();
    const invocation = isFunction
      ? new RegExp(`\\b${name}\\s*\\(`)
      : new RegExp(`<${name}(?:\\s|/|>)`);
    if (!parent.includes(`from "./${path}"`) || !invocation.test(parent)) {
      throw new Error(`${parentPath} no longer wires ${name}`);
    }
    return readWhatsAppSource(`../workspace/${path}.ts${isFunction ? "" : "x"}`);
  })].join("\n");
}

/** Follow only the three live controller calls; unrelated hooks cannot satisfy checks. */
export function readComposerControllerSource() {
  const controller = readWiredOwners("../workspace/use-message-composer.ts", [
    ["useMessageComposerPreview", "use-message-composer-preview"],
    ["useComposerHeaderImage", "use-composer-header-image"],
    ["useMessageComposerSend", "use-message-composer-send"],
  ]);
  return `${controller}\n${readWiredOwners("../workspace/use-message-composer-preview.ts", [
    ["composerFieldState", "composer-field-state"],
    ["resolveComposerDraft", "composer-draft"],
  ])}`;
}

export function readComposerViewSource() {
  return readWiredOwners("../workspace/message-composer.tsx", [
    ["MessageComposerEditor", "message-composer-editor"],
    ["MessageComposerFeedback", "message-composer-feedback"],
    ["MessageComposerReviewDialog", "message-composer-review-dialog"],
  ]);
}

export function readComposerAudienceSource() {
  return readWiredOwners("../workspace/message-composer-audience.tsx", [
    ["ComposerAudienceFilters", "message-composer-audience-filters"],
  ]);
}

export function readRecipientWorkspaceSource() {
  return `${readWiredOwners("../workspace/recipients-page.tsx", [
    ["useRecipientRoster", "use-recipient-roster"],
    ["RecipientRosterFilters", "recipient-roster-filters"],
    ["RecipientRosterTable", "recipient-roster-table"],
  ])}\n${readWiredOwners("../workspace/use-recipient-roster.ts", [
    ["recipientPeople", "recipient-roster-model"],
    ["recipientWelcomeSummary", "recipient-roster-model"],
    ["openRecipientDetails", "recipient-roster-model"],
  ])}`;
}

export function readRecipientDetailSource() {
  return readWiredOwners("../workspace/recipient-details-rail.tsx", [
    ["detailLabel", "recipient-roster-model"],
  ]);
}

/** Read only the public facade's explicitly wired transport/type owners. */
export function readWhatsAppApiSource() {
  const facade = readWhatsAppSource("../api/whatsapp.api.ts");
  const transports = ["groups", "recipients", "message-reads", "media"];
  const source = transports.map((owner) => {
    const relativeModule = `broadcast-${owner}.api`;
    if (!facade.includes(`from './${relativeModule}'`)) throw new Error(`Facade no longer wires ${relativeModule}`);
    return readWhatsAppSource(`../api/${relativeModule}.ts`);
  });
  for (const owner of ["recipients", "groups", "messages"]) {
    if (!facade.includes(`export type * from '../types/${owner}'`)) throw new Error(`Facade no longer exposes ${owner} types`);
    source.push(readWhatsAppSource(`../types/${owner}.ts`));
  }
  return [facade, ...source].join("\n");
}
