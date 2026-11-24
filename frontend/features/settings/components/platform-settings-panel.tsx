"use client";

import { usePlatformSettings } from "../hooks/use-platform-settings";
import { usePlatformDataPurge } from "../hooks/use-platform-data-purge";
import { PlatformPolicySection } from "./platform-policy-section";
import { PlatformDataSection } from "./platform-data-section";

export function PlatformSettingsPanel({ section }: { section: "policies" | "data" }) {
  const controller = usePlatformSettings();
  const purge = usePlatformDataPurge(controller.canPurge);
  return (
    <div className="flex flex-col gap-5">
      {section === "policies" ? (
        <PlatformPolicySection controller={controller} />
      ) : (
        <PlatformDataSection controller={controller} purge={purge} />
      )}
    </div>
  );
}
