import { useState } from "react";
import { createRoot } from "react-dom/client";
import "../../app/globals.css";
import { ReplacementRecipientChoice } from "../../features/passports/components/replacement-recipient-choice";
import type { ReplacementCandidate } from "../../features/passports/api/upload-links.api";

const candidates: ReplacementCandidate[] = ["Alpha", "SYNTHETICLONGNAME".repeat(12), "Gamma"].map((name, index) => ({
  recipient_id: `recipient-${index}`, recipient_ids: [`recipient-${index}`], name,
  phone: `+91900000000${index}`, broadcast_ids: ["synthetic"],
  broadcast_names: ["Synthetic roster"], imported_fields: { producer_code: `CODE-${index}` },
}));

function Fixture() {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <main className="mx-auto w-full max-w-3xl p-4">
      <div role="radiogroup" aria-label="Synthetic recipients" className="space-y-2">
        {candidates.map((candidate) => (
          <ReplacementRecipientChoice key={candidate.recipient_id} candidate={candidate}
            isSelected={selected === candidate.recipient_id} disabled={false}
            groupName="synthetic-recipient" onSelect={setSelected} />
        ))}
      </div>
      <output aria-label="Selected recipient">{selected ?? "None"}</output>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
